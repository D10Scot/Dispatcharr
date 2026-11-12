"""``MINO_PASSWORD_LOGIN_FORCE`` is read once into ``settings.PASSWORD_LOGIN_FORCE`` (SSO spec 5.6).

Exactly ``1`` turns it on; any other value is ignored with one WARNING. Each case imports the
production settings in a child interpreter, so it is isolated from the running suite's
already-imported settings and environment.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WARNING = "MINO_PASSWORD_LOGIN_FORCE is set to a value other than 1 and is ignored"


def _child(value):
    env = {k: v for k, v in os.environ.items() if k != "MINO_PASSWORD_LOGIN_FORCE"}
    if value is not None:
        env["MINO_PASSWORD_LOGIN_FORCE"] = value
    env["DJANGO_SETTINGS_MODULE"] = "dispatcharr.settings"
    code = "import dispatcharr.settings as s; print('MARKER', repr(s.PASSWORD_LOGIN_FORCE))"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise AssertionError(f"child failed: {out.stderr[-800:]}")
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("MARKER ")][-1]
    return line.split()[1], out.stderr


class PasswordLoginForceSettingTests(unittest.TestCase):
    def test_exactly_one_turns_it_on(self):
        value, stderr = _child("1")
        self.assertEqual(value, "True")
        self.assertNotIn(WARNING, stderr)

    def test_unset_is_off_without_a_warning(self):
        value, stderr = _child(None)
        self.assertEqual(value, "False")
        self.assertNotIn(WARNING, stderr)

    def test_any_other_value_is_ignored_with_a_warning(self):
        for raw in ("true", "yes", "0", "", " 1"):
            with self.subTest(raw=raw):
                value, stderr = _child(raw)
                self.assertEqual(value, "False", f"{raw!r} turned the override on")
                self.assertEqual(stderr.count(WARNING), 1, stderr[-800:])
