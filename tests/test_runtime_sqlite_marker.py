"""``settings.RUNTIME_SQLITE`` marks a LIVE SQLite database (SSO spec 4.4, PR S0).

Each case imports settings in a child interpreter so it is isolated from the running suite's
already-imported settings and environment.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _child(module, *, db_engine=None, test_use_sqlite=None):
    env = {k: v for k, v in os.environ.items() if k not in ("DB_ENGINE", "TEST_USE_SQLITE")}
    if db_engine is not None:
        env["DB_ENGINE"] = db_engine
    if test_use_sqlite is not None:
        env["TEST_USE_SQLITE"] = test_use_sqlite
    env["DJANGO_SETTINGS_MODULE"] = module
    code = (
        f"import {module} as s; "
        "print('MARKER', repr(s.RUNTIME_SQLITE), s.DATABASES['default']['ENGINE'])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise AssertionError(f"child failed: {out.stderr[-800:]}")
    # settings import prints boot noise; the answer is the MARKER line
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("MARKER ")][-1]
    return line.split()[1:]


class RuntimeSqliteMarkerTests(unittest.TestCase):
    def test_settings_marks_runtime_sqlite(self):
        self.assertEqual(_child("dispatcharr.settings", db_engine="sqlite")[0], "True")

    def test_settings_without_db_engine_is_not_runtime_sqlite(self):
        self.assertEqual(_child("dispatcharr.settings")[0], "False")

    def test_test_settings_reset_the_marker_under_inherited_db_engine(self):
        with self.subTest(selection="TEST_USE_SQLITE=1"):
            sqlite = _child(
                "dispatcharr.settings_test", db_engine="sqlite", test_use_sqlite="1"
            )
            self.assertEqual(sqlite, ["False", "django.db.backends.sqlite3"])
        with self.subTest(selection="TEST_USE_SQLITE unset"):
            pg = _child("dispatcharr.settings_test", db_engine="sqlite")
            self.assertEqual(pg, ["False", "django.db.backends.postgresql"])
