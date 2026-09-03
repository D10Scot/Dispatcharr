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

MARKED_IGNORE = '''
import logging

logger = logging.getLogger(__name__)


def go():
    logger.warning("get_stream_url() returned None")  # credential-logging: ignore - no value
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

    def test_ignore_marker_clears_a_call(self):
        path = self.write("marked.py", MARKED_IGNORE)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
