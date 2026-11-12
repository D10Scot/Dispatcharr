"""The entrypoint hands the CLI the variables the web tier has (SSO spec 5.6).

A ``docker exec ... su - dispatch -c`` shell gets only the variables the entrypoint writes to
``/etc/profile.d``. The optional-variable loop propagates a variable only when it is set, so
a switch missing from that loop is on in the web tier and silently off for ``manage.py``.
"""

import re
import unittest
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker" / "entrypoint.sh"

# Names the SSO spec requires in the loop. PR S4 adds MINO_PASSWORD_LOGIN_FORCE.
REQUIRED_OPTIONAL = ["MINO_OIDC_ALLOW_HTTP"]


def optional_variable_loop(text):
    match = re.search(r"for _opt_var in (.*?); do", text, re.DOTALL)
    if match is None:
        raise AssertionError("the optional-variable loop was not found in docker/entrypoint.sh")
    return set(match.group(1).replace("\\", " ").split())


class EntrypointEnvPropagationTests(unittest.TestCase):
    def test_loop_exists_and_parses(self):
        names = optional_variable_loop(ENTRYPOINT.read_text())
        self.assertIn("POSTGRES_SSL", names, "the parser read the wrong loop")

    def test_sso_switches_are_propagated_to_login_shells(self):
        names = optional_variable_loop(ENTRYPOINT.read_text())
        for name in REQUIRED_OPTIONAL:
            self.assertIn(
                name,
                names,
                f"{name} is missing from the entrypoint's optional-variable loop, so "
                "manage.py run through `su -` would not see it",
            )

    def test_auth_switches_reach_login_shells(self):
        # PR S4: the break-glass switch. Without it in the loop, `password_login --status`
        # run through `su -` reports the override off while the web tier has it on.
        names = optional_variable_loop(ENTRYPOINT.read_text())
        for name in ("MINO_OIDC_ALLOW_HTTP", "MINO_PASSWORD_LOGIN_FORCE"):
            self.assertIn(
                name,
                names,
                f"{name} is missing from the entrypoint's optional-variable loop, so "
                "manage.py run through `su -` would not see it",
            )
