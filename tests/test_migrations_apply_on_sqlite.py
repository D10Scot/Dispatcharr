"""The full migration graph must apply on SQLite, not only PostgreSQL.

Two migrations run raw PostgreSQL SQL with no vendor guard
(`apps/channels/migrations/0038_add_catchup_fields.py` and
`apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py`), which
stops `TEST_USE_SQLITE=1 manage.py test` from ever creating a test database
(#191). This spawns a real `manage.py migrate` against an in-memory SQLite
database in a subprocess, so a regression here fails loudly instead of being
masked by whatever fixture state the running test process already holds.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SqliteMigrationGraphTests(SimpleTestCase):
    def test_full_migration_graph_applies_on_sqlite(self):
        manage_py = Path(settings.BASE_DIR) / "manage.py"
        env = {
            **os.environ,
            "TEST_USE_SQLITE": "1",
            "DJANGO_SETTINGS_MODULE": "dispatcharr.settings_test",
        }
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(manage_py),
                    "migrate",
                    "--noinput",
                    "-v0",
                ],
                cwd=settings.BASE_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(
                "manage.py migrate against an in-memory SQLite database did "
                f"not finish within {exc.timeout:.0f}s (a normal run takes "
                "2.3-2.8s). stderr tail:\n"
                + (exc.stderr or "")[-4000:]
            )
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "manage.py migrate against an in-memory SQLite database failed "
                f"(exit {result.returncode}). stderr tail:\n"
                + result.stderr[-4000:]
            ),
        )
