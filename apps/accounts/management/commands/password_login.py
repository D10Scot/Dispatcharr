"""``manage.py password_login --enable | --disable [--force] | --status`` (SSO spec 5.6).

The break-glass path that needs no restart. It writes ``auth_settings.password_login_enabled``
through ``CoreSettings._update_group`` inside the same locking transaction as the lockout guard
(``select_for_update`` on the ``auth_settings`` row, spec 5.5). Every password gate reads the
row fresh, so the change is live at the next request.

A management command has no URL, and nothing in the web tier invokes it. Run it in the
container through a login shell, which is what loads ``DJANGO_SECRET_KEY``:

    docker exec <container> su - dispatch -c 'cd /app && python manage.py password_login --status'

``--disable`` keeps one floor: at least one enabled provider, unless ``--force``. It cannot
apply the guard's rule, because the command line has no SSO session. On a runtime SQLite
database ``--disable`` is refused outright, ``--force`` included (spec 4.4).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import password_login
from apps.accounts.models import OIDCProvider, User
from apps.accounts.oidc import audit, auth_settings, expiry, guard
from core.models import AUTH_SETTINGS_KEY, CoreSettings

RECOVERY_DOC = "docs/sso-recovery.md"


def admins_with_usable_password():
    """How many active admins could sign in with a password now."""
    admins = User.objects.filter(is_active=True, user_level__gte=User.UserLevel.ADMIN)
    return sum(1 for user in admins.only("password") if user.has_usable_password())


def _on_off(value):
    return "on" if value else "off"


class Command(BaseCommand):
    help = (
        "Turn password login on or off, or report its state (SSO break-glass). "
        f"See {RECOVERY_DOC}."
    )

    def add_arguments(self, parser):
        verb = parser.add_mutually_exclusive_group(required=True)
        verb.add_argument("--enable", action="store_true", help="Turn password login on.")
        verb.add_argument(
            "--disable",
            action="store_true",
            help="Turn password login off. Refused unless a provider is enabled.",
        )
        verb.add_argument(
            "--status",
            action="store_true",
            help="Print the stored value, the environment override, the enabled providers "
            "and how many active admins have a usable password.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="With --disable: turn password login off even with no enabled provider.",
        )

    def handle(self, *args, **options):
        if options["force"] and not options["disable"]:
            raise CommandError("--force applies only to --disable")
        if options["status"]:
            self._status()
        elif options["enable"]:
            changed = self._write(True)
            self.stdout.write(
                "Password login enabled." if changed else "Password login was already enabled."
            )
            self._report_admins()
        else:
            self._disable(force=options["force"])

    # ---- writes ---------------------------------------------------------------------

    def _write(self, enabled, *, check_floor=False):
        """Set the stored value under the auth_settings row lock. Returns whether it changed."""
        with transaction.atomic():
            row = auth_settings.lock_row()
            values = auth_settings.row_values(row)
            if values["password_login_enabled"] == enabled:
                return False
            if check_floor and not OIDCProvider.objects.filter(enabled=True).exists():
                raise CommandError(
                    f"refused: {guard.LAST_ENABLED_PROVIDER}: no provider is enabled, so "
                    "nobody could sign in once password login is off. Enable a provider "
                    "first, or pass --force to turn password login off anyway."
                )
            CoreSettings._update_group(
                AUTH_SETTINGS_KEY, auth_settings.ROW_NAME, {"password_login_enabled": enabled}
            )
            audit.record_config_change(
                audit.ACTION_SETTINGS_UPDATED,
                user="cli",
                provider=None,
                fields=["password_login_enabled"],
            )
        return True

    def _disable(self, *, force):
        if settings.RUNTIME_SQLITE:
            # Spec 4.4: the lock this depends on is a PostgreSQL guarantee; no --force past it.
            raise CommandError(
                "refused: requires_postgresql: password login cannot be turned off on a "
                "SQLite database."
            )
        changed = self._write(False, check_floor=not force)
        self.stdout.write(
            "Password login disabled." if changed else "Password login was already disabled."
        )
        if password_login.forced():
            self.stdout.write(
                "MINO_PASSWORD_LOGIN_FORCE is on in this environment, so password login "
                "stays on until it is removed."
            )

    # ---- reports --------------------------------------------------------------------

    def _report_admins(self):
        count = admins_with_usable_password()
        self.stdout.write(f"Active admins with a usable password: {count}")
        if count == 0:
            self.stdout.write(
                "No admin can sign in with a password yet. Give one a password with "
                "`python manage.py changepassword <admin-username>`, or create a new admin "
                f"with `python manage.py createsuperuser`. See {RECOVERY_DOC}."
            )

    def _status(self):
        stored = password_login.stored_enabled()
        forced = password_login.forced()
        self.stdout.write(f"Password login (stored): {'enabled' if stored else 'disabled'}")
        self.stdout.write(f"MINO_PASSWORD_LOGIN_FORCE: {_on_off(forced)}")
        self.stdout.write(
            f"Password login now: {'enabled' if (stored or forced) else 'disabled'}"
        )
        providers = list(OIDCProvider.objects.filter(enabled=True).order_by("id"))
        self.stdout.write(f"Enabled providers: {len(providers)}")
        for provider in providers:
            info = expiry.credential_expiry(provider)
            line = f"  {provider.slug}: credential {info['state']}"
            if info["expires_at"] and info["days_left"] < 0:
                line += f", expired on {info['expires_at']}"
            elif info["expires_at"]:
                line += f", expires {info['expires_at']} ({info['days_left']} days left)"
            self.stdout.write(line)
        self._report_admins()
