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

MARKED_WITHOUT_A_REASON = '''
import logging

logger = logging.getLogger(__name__)


def go(account):
    logger.debug(  # credential-logging: ignore
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

# Observability spec D9: telemetry calls are sinks too.
SPAN_LEAK = '''
from opentelemetry import trace

span = trace.get_current_span()


def go(stream_url):
    span.set_attribute("url", stream_url)
'''

SPAN_REDACTED = '''
from opentelemetry import trace

from dispatcharr.observability.redaction import redact_text

span = trace.get_current_span()


def go(stream_url):
    span.set_attribute("url", redact_text(stream_url))
'''

SPAN_CLEAN = '''
from opentelemetry import trace

span = trace.get_current_span()


def go(channel_pk):
    span.set_attribute("mino.channel_id", channel_pk)
'''

INSTRUMENT_LEAK = '''
def go(self, stream_url, seconds):
    self._task_histogram.record(seconds, {"url": stream_url})
'''

NOT_A_TELEMETRY_RECEIVER = '''
def go(cache, stream_url):
    cache.set("k", stream_url)
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

    def test_ignore_marker_without_a_reason_does_not_clear_a_call(self):
        # An exemption nobody has to justify is not reviewable.
        path = self.write("bare_marker.py", MARKED_WITHOUT_A_REASON)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn(f"{path}:7:", result.stdout)
        self.assertIn("needs a reason", result.stdout)

    def test_a_redact_url_comment_does_not_clear_a_call(self):
        # The exclusion is anchored to a real call, not the bare substring.
        path = self.write("fake.py", FAKE_REDACT_COMMENT)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:7:", result.stdout)

    def test_a_span_attribute_naming_a_url_is_reported(self):
        path = self.write("span_leak.py", SPAN_LEAK)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn(f"{path}:7:", result.stdout)
        self.assertIn("set_attribute", result.stdout)

    def test_a_span_attribute_through_redact_text_is_clean(self):
        path = self.write("span_ok.py", SPAN_REDACTED)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_span_attribute_naming_nothing_credential_like_is_clean(self):
        path = self.write("span_clean.py", SPAN_CLEAN)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_an_instrument_record_naming_a_url_is_reported(self):
        path = self.write("instrument_leak.py", INSTRUMENT_LEAK)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:2:", result.stdout)

    def test_a_set_call_on_a_non_telemetry_receiver_is_not_a_telemetry_call(self):
        # `set` is a telemetry method name, but `cache` is not a telemetry receiver.
        path = self.write("cache_set.py", NOT_A_TELEMETRY_RECEIVER)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

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


# The bare-name and TRACE rules. Each source is (name, source, reported lines).
HEADER = "import logging\nfrom dispatcharr.utils import redact_url, redact_text\nlogger = logging.getLogger(__name__)\n"

NAME_CASES = (
    ("bare url, percent form", 'logger.debug("fetch %s", url)', True),
    ("bare url, f-string", 'logger.debug(f"fetch {url}")', True),
    ("bare url, attribute", 'logger.info("fetch %s", repo.url)', True),
    ("bare url, redact_url", 'logger.debug("fetch %s", redact_url(url))', False),
    ("bare url, f-string redact_url", 'logger.debug(f"fetch {redact_url(url)}")', False),
    ("bare url, redact_text", 'logger.debug("fetch %s", redact_text(url))', False),
    ("url only in message text", 'logger.info(f"Generated stream url: {redact_url(u)}")', False),
    ("pattern, percent form", 'logger.debug("using %s", search_pattern)', True),
    ("pattern, f-string", 'logger.debug(f"using {replace_pattern!r}")', True),
    ("bare pattern, attribute", 'logger.warning("using %s", flt.pattern)', True),
    ("pattern, redact_text", 'logger.debug("using %s", redact_text(search_pattern))', False),
    ("pattern only in message text", 'logger.info(f"Custom pattern did not match {name}")', False),
    ("trace, bare url", 'logger.trace("fetch %s", url)', True),
    ("trace, f-string url", 'logger.trace(f"fetch {stream_url}")', True),
    ("trace, pattern", 'logger.trace("using %s", search_pattern)', True),
    ("trace, redacted", 'logger.trace("fetch %s", redact_url(url))', False),
    ("format field attribute", 'logger.info("{0.search_pattern}".format(profile))', True),
    ("format field with conversion", 'logger.info("{0.url!s}".format(obj))', True),
    ("format named field", 'logger.info("{o.url}".format(o=obj))', True),
    ("format of a redacted value", 'logger.info("{}".format(redact_url(url)))', False),
    ("format fields naming nothing", 'logger.info("{0.name} {1}".format(obj, n))', False),
    ("lazy mapping template", 'logger.info("%(url)s", row)', True),
    ("lazy mapping template, other key", 'logger.info("%(name)s", row)', False),
    ("lazy mapping, escaped percent", 'logger.info("%%(url)s", row)', False),
    ("escaped percent then a real key", 'logger.info("%%%(url)s" % row)', True),
    ("inline dict, redacted value", 'logger.info("%(url)s", {"url": redact_url(u)})', False),
    ("inline dict, raw value", 'logger.info("%(url)s", {"url": u})', True),
    ("inline dict, innocent-looking raw value", 'logger.info("%(url)s", {"url": value})', True),
    ("inline dict, one redacted one raw", 'logger.info("%(url)s %(search_pattern)s", {"url": redact_url(u), "search_pattern": p})', True),
    ("inline dict, both redacted", 'logger.info("%(url)s %(search_pattern)s", {"url": redact_url(u), "search_pattern": redact_text(p)})', False),
    ("inline dict, key not selected", 'logger.info("%(name)s", {"name": n, "url": redact_url(u)})', False),
    # DOCUMENTED CONSERVATIVE FALSE POSITIVE (see the checker's KNOWN GAPS): a
    # keyword-supplied .format field is not traced to its redacted value. Pinned
    # so a change in this behaviour is deliberate; the safe form passes the
    # redacted value positionally.
    ("format keyword field, redacted value (known false positive)", 'logger.info("{search_pattern}".format(search_pattern=redact_text(p)))', True),
    ("format positional field, redacted value", 'logger.info("{}".format(redact_text(p)))', False),
    ("inline dict spread", 'logger.info("%(url)s", {**row})', True),
    ("eager inline dict, redacted", 'logger.info("%(url)s" % {"url": redact_url(u)})', False),
    ("eager inline dict, raw", 'logger.info("%(url)s" % {"url": u})', True),
    ("eager inline dict, one redacted one raw", 'logger.info("%(url)s %(search_pattern)s" % {"url": redact_url(u), "search_pattern": p})', True),
    ("eager non-inline mapping", 'logger.info("%(url)s" % row)', True),
    ("escaped percent is text", 'logger.info("%%(url)s %s" % name)', False),
    ("percent mapping key applied", 'logger.info("%(url)s" % row)', True),
    # Template keys are judged by the credential rule as well as the name rule.
    ("lazy mapping, credential key access_token", 'logger.info("%(access_token)s", row)', True),
    ("lazy mapping, credential key password", 'logger.info("%(password)s", row)', True),
    ("lazy inline dict, credential key, raw value", 'logger.info("%(password)s", {"password": p})', True),
    ("lazy inline dict, credential key, redacted value", 'logger.info("%(password)s", {"password": redact_text(p)})', False),
    ("lazy inline dict, credential key redacted, neighbour raw", 'logger.info("%(password)s %(name)s", {"password": redact_text(p), "name": request.headers})', True),
    ("lazy mapping, escaped credential key", 'logger.info("%%(password)s", row)', False),
    ("eager mapping, credential key", 'logger.info("%(access_token)s" % row)', True),
    ("eager inline dict, credential key, raw value", 'logger.info("%(password)s" % {"password": p})', True),
    ("getattr literal", 'logger.info("%s", getattr(obj, "url"))', True),
    ("getattr literal pattern", 'logger.info("%s", getattr(obj, "search_pattern", None))', True),
    ("getattr redacted", 'logger.info("%s", redact_url(getattr(obj, "url")))', False),
    ("getattr other name", 'logger.info("%s", getattr(obj, "name"))', False),
    ("subscript literal", 'logger.info("%s", row["url"])', True),
    ("dict get literal", 'logger.info("%s", row.get("search_pattern"))', True),
    ("dict get other key", 'logger.info("%s", row.get("name"))', False),
    ("extra mapping value", 'logger.info("fetch", extra={"value": url})', True),
    ("extra mapping redacted", 'logger.info("fetch", extra={"value": redact_url(url)})', False),
    ("extra mapping key only", 'logger.info("fetch", extra={"url": name})', False),
    ("trace, nothing credential-like", 'logger.trace("started %s", name)', False),
)


class WidenedNameRuleTests(SimpleTestCase):
    """Bare `url`, `pattern`/`*_pattern` and `logger.trace` (R15)."""

    setUp = CredentialLoggingGuardTests.setUp
    write = CredentialLoggingGuardTests.write
    run_guard = CredentialLoggingGuardTests.run_guard

    def run_case(self, source):
        path = self.write("case.py", HEADER + "def go():\n    " + source + "\n")
        return self.run_guard(path)

    def test_each_name_and_trace_case(self):
        for label, source, reported in NAME_CASES:
            with self.subTest(label):
                result = self.run_case(source)
                detail = (
                    f"{label}: {source}\nreturncode={result.returncode}\n"
                    f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
                )
                if reported:
                    self.assertEqual(result.returncode, 1, f"not reported\n{detail}")
                    self.assertEqual(
                        len(result.stdout.splitlines()), 1, f"expected one finding\n{detail}"
                    )
                else:
                    self.assertEqual(result.returncode, 0, f"wrongly reported\n{detail}")
                    self.assertEqual(result.stderr, "", f"unexpected stderr\n{detail}")

    def test_a_marker_with_a_reason_clears_a_bare_name(self):
        result = self.run_case(
            'logger.debug("using %s", search_pattern)  # credential-logging: ignore - presence only'
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_marker_without_a_reason_does_not_clear_a_bare_name(self):
        result = self.run_case(
            'logger.trace("using %s", search_pattern)  # credential-logging: ignore'
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("needs a reason", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_the_source_tree_is_clean_under_the_widened_rule(self):
        # A live ratchet over every backend source file, not a fixture.
        repo = GUARD.resolve().parent.parent
        targets = sorted(
            p
            for top in ("apps", "core", "dispatcharr")
            for p in (repo / top).rglob("*.py")
        )
        self.assertGreater(len(targets), 100)
        result = self.run_guard(*targets)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The CLI only warns about a file it cannot read or parse and still
        # exits 0, so a skipped file would pass the line above unseen.
        self.assertEqual(result.stderr, "", "a file was not scanned")

    def test_a_marker_inside_a_string_does_not_clear_a_call(self):
        for label, source in (
            ("message string", 'logger.info("credential-logging: ignore - demo %s", url)'),
            (
                "multiline string",
                'logger.info("""\ncredential-logging: ignore - demo\n%s""", url)',
            ),
            (
                "docstring beside the call",
                '"""credential-logging: ignore - demo"""\n    logger.info("%s", url)',
            ),
        ):
            with self.subTest(label):
                result = self.run_case(source)
                self.assertEqual(result.returncode, 1, f"{label} cleared the call")
                self.assertIn("case.py:", result.stdout, f"{label}: no finding line")
                self.assertEqual(result.stderr, "", f"{label}: the checker crashed")

    def test_a_marker_in_a_real_comment_on_any_spanned_line_clears_a_call(self):
        result = self.run_case(
            'logger.info(\n        "%s",  # credential-logging: ignore - demo reason\n        url,\n    )'
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_marker_on_a_line_the_call_does_not_span_clears_nothing(self):
        result = self.run_case(
            '# credential-logging: ignore - demo reason\n    logger.info("%s", url)'
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("case.py:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_one_marker_cannot_clear_two_calls_on_one_line(self):
        result = self.run_case(
            'logger.info("%s", url); logger.info("%d", len(name))'
            '  # credential-logging: ignore - length only'
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ambiguous", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_one_marker_cannot_clear_a_nested_logging_call(self):
        result = self.run_case(
            'logger.info("%s", [logger.debug("%s", url)])'
            '  # credential-logging: ignore - demo reason'
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ambiguous", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_a_marker_on_its_own_single_call_line_still_clears(self):
        result = self.run_case(
            'logger.info("%s", url)  # credential-logging: ignore - demo reason\n'
            '    logger.info("%s", url)  # credential-logging: ignore - demo reason'
        )
        self.assertEqual(result.returncode, 0, result.stdout)


OIDC_CREDENTIAL_NAMES = (
    "client_secret",
    "client_assertion",
    "client_key",
    "id_token",
    "access_token",
    "refresh_token",
    "code_verifier",
    "nonce",
)


class OidcCredentialNamesTests(SimpleTestCase):
    """SSO spec 3.3, T16: CREDENTIAL_RE knows the OIDC flow's secrets, one case per name."""

    setUp = CredentialLoggingGuardTests.setUp
    write = CredentialLoggingGuardTests.write
    run_guard = CredentialLoggingGuardTests.run_guard

    def assertReported(self, name, source):
        path = self.write(f"{name}.py", source)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, f"{name}: {result.stdout + result.stderr}")
        self.assertIn(name, result.stdout)

    def test_client_secret(self):
        self.assertReported("client_secret", 'logger.info("secret %s", client_secret)\n')

    def test_client_assertion(self):
        self.assertReported("client_assertion", 'logger.debug("assertion %s", client_assertion)\n')

    def test_client_key(self):
        self.assertReported("client_key", 'logger.warning(f"key {provider.client_key_encrypted}")\n')

    def test_id_token(self):
        self.assertReported("id_token", 'logger.info("token %s", id_token)\n')

    def test_access_token(self):
        self.assertReported("access_token", 'logger.error("got %s", body["access_token"])\n')

    def test_refresh_token(self):
        self.assertReported("refresh_token", 'logger.debug("refresh %s", refresh_token)\n')

    def test_code_verifier(self):
        self.assertReported("code_verifier", 'logger.info("pkce %s", code_verifier)\n')

    def test_nonce(self):
        self.assertReported("nonce", 'logger.info("nonce %s", nonce)\n')

    def test_nonce_is_matched_as_a_word(self):
        path = self.write("nonces.py", 'logger.info("count %s", nonces_seen)\n')
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_id_token_inside_a_longer_name(self):
        self.assertReported("raw_id_token", 'logger.info("token %s", raw_id_token)\n')

    def test_id_token_is_not_matched_inside_valid_token(self):
        for name in ("valid_token", "invalid_token"):
            with self.subTest(name=name):
                path = self.write(f"{name}.py", f'logger.info("x %s", {name})\n')
                result = self.run_guard(path)
                self.assertEqual(
                    result.returncode, 0,
                    f"{name} was reported as an ID token: {result.stdout + result.stderr}",
                )

    def test_every_name_is_covered(self):
        tested = {n[len("test_"):] for n in dir(self) if n.startswith("test_")}
        self.assertLessEqual(set(OIDC_CREDENTIAL_NAMES), tested)

    def test_the_oidc_package_is_clean(self):
        repo = GUARD.resolve().parent.parent
        targets = sorted((repo / "apps" / "accounts" / "oidc").glob("*.py"))
        targets.append(repo / "apps" / "accounts" / "api_views.py")
        result = self.run_guard(*targets)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
