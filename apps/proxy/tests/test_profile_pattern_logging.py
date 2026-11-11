"""An M3U profile's search and replace patterns must never reach a log.

THE DEFECT. In the Xtream "simple" profile mode the UI builds `search_pattern`
as `<username>/<password>` and `replace_pattern` as
`<newUsername>/<newPassword>` (frontend/src/utils/forms/M3uProfileUtils.js,
`applyXcSimplePatterns`), so the patterns ARE the provider login.
`next_source.transform_url` logged them at DEBUG, logged the search pattern in
its no-match WARNING (on by default), and logged `{e}` at ERROR.

These tests call the real helpers with credential-bearing patterns, capture
every record at DEBUG on the module loggers, and fail naming the leaked value.
"""

import contextlib
import logging
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from apps.proxy import next_source
from apps.proxy.vod_proxy import views as vod_views

SEARCH = "olduser/oldpass"
REPLACE = "newuser/newpass"
SECRETS = ("olduser", "oldpass", "newuser", "newpass", SEARCH, REPLACE)
URL = "http://prov.example.com/live/olduser/oldpass/1.ts"


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def capture(*loggers):
    """Collect every record the given loggers emit, at DEBUG.

    Attached to the module loggers themselves because their records do not
    reach the root logger under this project's logging config, so a root
    `assertLogs()` would see nothing. Fails if nothing at all was emitted, so
    a test cannot pass by capturing nothing.
    """
    handler = _Records()
    saved = []
    for lg in loggers:
        saved.append((lg, lg.level))
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
    try:
        yield handler
    finally:
        for lg, level in saved:
            lg.removeHandler(handler)
            lg.setLevel(level)
    assert handler.records, "no log record captured: the capture is vacuous"


def record_text(record):
    return " | ".join(
        [record.getMessage(), repr(record.args), record.exc_text or ""]
    )


class NoPatternInLogs:
    """Mixin: run `capture()` and assert no record carries a secret."""

    def assert_no_leak(self, logs):
        for rec in logs.records:
            text = record_text(rec)
            for secret in SECRETS:
                self.assertNotIn(
                    secret,
                    text,
                    f"{rec.name} {rec.levelname} leaked {secret!r}: {text}",
                )
            self.assertIsNone(rec.exc_info, f"{rec.name} attached a traceback")


class TransformUrlPatternLoggingTests(NoPatternInLogs, SimpleTestCase):
    def test_transform_url_match_logs_no_pattern(self):
        with capture(next_source.logger) as logs:
            out = next_source.transform_url(URL, SEARCH, REPLACE)
        self.assertEqual(out, "http://prov.example.com/live/newuser/newpass/1.ts")
        self.assert_no_leak(logs)

    def test_transform_url_no_match_warning_logs_no_pattern(self):
        with capture(next_source.logger) as logs:
            out = next_source.transform_url(URL, "zzuser/zzpass", REPLACE)
        self.assertEqual(out, URL)
        self.assertTrue(
            any(r.levelname == "WARNING" for r in logs.records),
            "the no-match WARNING must still be emitted",
        )
        with capture(next_source.logger) as logs2:
            next_source.transform_url(URL, "olduser/other", REPLACE)
        self.assert_no_leak(logs2)

    def test_transform_url_malformed_pattern_logs_no_pattern(self):
        with capture(next_source.logger) as logs:
            out = next_source.transform_url(URL, "olduser/(oldpass", REPLACE)
        self.assertEqual(out, URL)
        self.assert_no_leak(logs)

    def test_transform_url_error_logs_type_only_not_exception_text(self):
        # The `regex` module's own errors carry only a position, never the
        # pattern (probed: ~18 malformed shapes, none quoted it), so the
        # exception text is simulated: `re` quotes group names, and a future
        # `regex` could too.
        err = ValueError("bad group name 'olduser/oldpass' at position 4")
        with mock.patch.object(next_source.regex, "subn", side_effect=err):
            with capture(next_source.logger) as logs:
                out = next_source.transform_url(URL, SEARCH, REPLACE)
        self.assertEqual(out, URL)
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))


class VodTransformUrlPatternLoggingTests(NoPatternInLogs, SimpleTestCase):
    def profile(self, search=SEARCH, replace=REPLACE):
        return SimpleNamespace(search_pattern=search, replace_pattern=replace)

    def test_vod_transform_url_malformed_pattern_logs_no_pattern(self):
        with capture(vod_views.logger) as logs:
            out = vod_views._transform_url(URL, self.profile("olduser/(oldpass"))
        self.assertEqual(out, URL)
        self.assert_no_leak(logs)

    def test_vod_transform_url_error_logs_type_only(self):
        err = ValueError("bad group name 'olduser/oldpass' at position 4")
        with mock.patch("regex.sub", side_effect=err):
            with capture(vod_views.logger) as logs:
                out = vod_views._transform_url(URL, self.profile())
        self.assertEqual(out, URL)
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))
