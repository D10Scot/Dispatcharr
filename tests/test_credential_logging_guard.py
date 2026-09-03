"""Tests for scripts/check_credential_logging.py.

The guard is the thing that stops a future change from reintroducing the
credential leak this repo already shipped, so it needs its own coverage: an
earlier revision grepped physical lines and was silently blind to any logging
call wrapped across several lines, which is the shape Black produces by
default. The wrapped-leak case below is the regression test for exactly that.

The script is exercised as a subprocess, the way the edit hook and lint.yml
invoke it, so the exit codes and the "file:line: content" output format are
pinned as the contract they actually are.
"""

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from django.test import SimpleTestCase

GUARD = Path(__file__).resolve().parent.parent / "scripts" / "check_credential_logging.py"

ONE_LINE_LEAK = '''
import logging

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(f"Streaming from {final_stream_url}")
'''

WRAPPED_LEAK = '''
import logging

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(
        "[VOD-HEAD] Making request to provider: %s",
        final_stream_url,
    )
'''

WRAPPED_REDACTED = '''
import logging

from dispatcharr.utils import redact_url

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(
        "[VOD-HEAD] Making request to provider: %s",
        redact_url(final_stream_url),
    )
'''

CLEAN = '''
import logging

logger = logging.getLogger(__name__)


def go(channel_name, count):
    logger.info("Started %s with %s clients", channel_name, count)
'''

MIXED_ARGUMENTS = '''
import logging

from dispatcharr.utils import redact_url

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info("%s from %s", redact_url(final_stream_url), final_stream_url)
'''

MIXED_FSTRING = '''
import logging

from dispatcharr.utils import redact_url

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(f"{redact_url(final_stream_url)} came from {final_stream_url}")
'''

REDACTED_FSTRING = '''
import logging

from dispatcharr.utils import redact_url

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(f"{redact_url(final_stream_url)}")
'''

LITERAL_NAMING_A_URL_HELPER = '''
import logging

logger = logging.getLogger(__name__)


def go():
    logger.warning("[VOD-URL] get_stream_url() returned None")
    logger.error(f"[VOD-URL] no get_stream_url method")
'''

PRESENCE_CHECK = '''
import logging

logger = logging.getLogger(__name__)


def go(account):
    logger.debug("has password: %s", "yes" if account.password else "no")
'''

MARKED_IGNORE = '''
import logging

logger = logging.getLogger(__name__)


def go(account):
    logger.debug(  # credential-logging: ignore - presence only, never the value
        "has password: %s", "yes" if account.password else "no"
    )
'''

FAKE_REDACT_COMMENT = '''
import logging

logger = logging.getLogger(__name__)


def go(final_stream_url):
    logger.info(f"Streaming from {final_stream_url}")  # redact_url
'''

BROKEN_SYNTAX = '''
def go(:
'''


class CredentialLoggingGuardTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def write(self, name, source):
        path = self.tmpdir / name
        path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
        return path

    def run_guard(self, *paths):
        return subprocess.run(
            [sys.executable, str(GUARD), *[str(p) for p in paths]],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_guard_script_exists(self):
        self.assertTrue(GUARD.is_file(), f"{GUARD} is missing")

    def test_one_line_leak_is_reported(self):
        path = self.write("leak.py", ONE_LINE_LEAK)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn(f"{path}:7:", result.stdout)
        self.assertIn("final_stream_url", result.stdout)

    def test_wrapped_leak_is_reported(self):
        # The regression test: a physical-line grep sees "logger.info(" on one
        # line and the URL on another, and clears both.
        path = self.write("wrapped.py", WRAPPED_LEAK)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        # Reported at the line the call starts on, with the call joined.
        self.assertIn(f"{path}:7:", result.stdout)
        self.assertIn(
            'logger.info( "[VOD-HEAD] Making request to provider: %s", final_stream_url, )',
            result.stdout,
        )

    def test_wrapped_call_through_redact_url_is_clean(self):
        path = self.write("wrapped_ok.py", WRAPPED_REDACTED)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_clean_file_is_clean(self):
        path = self.write("clean.py", CLEAN)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_one_redacted_argument_does_not_clear_its_neighbour(self):
        # Judging the call as a whole let a single redact_url() anywhere in it
        # clear every other argument.
        path = self.write("mixed_args.py", MIXED_ARGUMENTS)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn(f"{path}:9:", result.stdout)

    def test_an_f_string_mixing_redacted_and_raw_is_reported(self):
        # An f-string is one argument, so a redacted interpolation in it cannot
        # clear a raw one beside it.
        path = self.write("mixed_fstring.py", MIXED_FSTRING)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn(f"{path}:9:", result.stdout)

    def test_an_f_string_interpolating_only_redact_url_is_clean(self):
        path = self.write("redacted_fstring.py", REDACTED_FSTRING)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_message_naming_a_url_helper_logs_no_value_and_is_clean(self):
        # A plain string, and an f-string with nothing interpolated, have no
        # expression to evaluate — neither can carry a credential.
        path = self.write("literal.py", LITERAL_NAMING_A_URL_HELPER)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_presence_check_naming_password_is_reported_without_a_marker(self):
        path = self.write("presence.py", PRESENCE_CHECK)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:7:", result.stdout)

    def test_ignore_marker_clears_a_call(self):
        # The same call as test_a_presence_check_..., marked.
        path = self.write("marked.py", MARKED_IGNORE)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_redact_url_comment_does_not_clear_a_call(self):
        # The exclusion is anchored to a real call, not the bare substring.
        path = self.write("fake.py", FAKE_REDACT_COMMENT)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:7:", result.stdout)

    def test_several_files_report_together_and_fail_once(self):
        leak = self.write("leak.py", ONE_LINE_LEAK)
        wrapped = self.write("wrapped.py", WRAPPED_LEAK)
        clean = self.write("clean.py", CLEAN)
        result = self.run_guard(clean, leak, wrapped)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 2, result.stdout)
        self.assertIn(str(leak), result.stdout)
        self.assertIn(str(wrapped), result.stdout)
        self.assertNotIn(str(clean), result.stdout)

    def test_non_python_arguments_are_skipped(self):
        path = self.tmpdir / "notes.txt"
        path.write_text("logger.info(f'{stream_url}')\n", encoding="utf-8")
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_file_warns_on_stderr_and_does_not_fail(self):
        missing = self.tmpdir / "gone.py"
        result = self.run_guard(missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("no such file", result.stderr)
        self.assertIn(str(missing), result.stderr)

    def test_unparseable_file_warns_on_stderr_and_does_not_fail(self):
        path = self.write("broken.py", BROKEN_SYNTAX)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("could not parse", result.stderr)

    def test_non_utf8_file_warns_on_stderr_and_does_not_fail(self):
        # UnicodeDecodeError is a ValueError, not an OSError: catching only
        # OSError made a latin-1 byte traceback out of the check.
        path = self.tmpdir / "latin1.py"
        path.write_bytes(b'logger.info(f"caf\xe9 {stream_url}")\n')
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not read", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_arguments_is_clean(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_repo_tree_this_pr_touches_is_clean(self):
        # A live ratchet, not a fixture: these are the files the PR redacted.
        repo = GUARD.resolve().parent.parent
        targets = [
            repo / "dispatcharr" / "utils.py",
            repo / "apps" / "m3u" / "tasks.py",
            repo / "apps" / "channels" / "tasks.py",
            repo / "apps" / "proxy" / "vod_proxy" / "views.py",
        ]
        result = self.run_guard(*targets)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
