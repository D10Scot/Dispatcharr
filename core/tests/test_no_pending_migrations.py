"""Project-wide guard: no app may have a model change with no migration.

#177: `core.StreamProfile.parameters` carried `blank=True` and a `help_text`
naming `{channelId}` with no migration recording either, since the last
migration touching the field (`core/migrations/0005`) predates both. Nothing
in CI ran `makemigrations --check`, so the drift went unnoticed. This test
runs that check for the whole project on every `core.tests` run.
"""

import io

from django.core.management import call_command
from django.test import TestCase


class NoPendingMigrationsTests(TestCase):
    def test_no_app_has_model_changes_without_a_migration(self):
        buf = io.StringIO()
        try:
            call_command("makemigrations", check=True, dry_run=True, stdout=buf)
        except SystemExit:
            self.fail(
                "makemigrations --check --dry-run found model changes with no "
                "migration:\n" + buf.getvalue()
            )
