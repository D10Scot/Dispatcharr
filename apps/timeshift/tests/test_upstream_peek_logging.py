"""Catch-up upstream diagnostics must log facts, never provider-controlled text.

THE DEFECT. `_stream_from_provider` logged, beside a correctly redacted URL, the
provider's raw `Content-Type` header (DEBUG cascade line) and `repr(peek[:120])`,
the first 120 bytes of the provider's response body (WARNING, on by default,
when the body is not MPEG-TS). A provider error page can quote the request URL,
login included, and a header is provider text too. The `credential-logging:
ignore` marker on each call justified only the redacted URL yet cleared the
whole call.

These tests drive the real function with a faked upstream whose Content-Type
and body both carry a fake credential-bearing URL, capture every record at
every level on the module logger, and capture inside `unscrubbed_logging()` so
the central scrubber cannot mask a regressed call site.
"""

import contextlib
import logging
from unittest import mock

from django.test import SimpleTestCase

from apps.timeshift import views
from tests.log_scrub_rig import unscrubbed_logging

LOGIN_URL = "http://example.invalid/timeshift/fakeuser/fakepass/60/2026-01-01:10-00/1.ts"
SECRETS = ("fakeuser", "fakepass", LOGIN_URL)
BODY_TEXT = "Error: denied for " + LOGIN_URL


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=1)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def capture():
    handler = _Records()
    lg = logging.getLogger(views.__name__)
    saved = lg.level
    lg.setLevel(1)
    lg.addHandler(handler)
    try:
        with unscrubbed_logging():
            yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(saved)


def _text(record):
    return " | ".join([record.getMessage(), repr(record.args), record.exc_text or ""])


class _FakeRaw:
    def __init__(self, body):
        self._body = body

    def read(self, _n):
        return self._body


class _FakeResponse:
    status_code = 200
    url = "http://example.invalid/portal"

    def __init__(self, content_type, body):
        self.headers = {"Content-Type": content_type}
        self.raw = _FakeRaw(body)

    def close(self):
        pass


def _run(content_type, body):
    kwargs = dict(
        candidate_urls=["http://example.invalid/portal"],
        user_agent="ua",
        range_header=None,
        virtual_channel_id="v",
        client_id="c",
        client_ip="127.0.0.1",
        client_user_agent="ua",
        user=None,
        channel_display_name="n",
        timestamp_utc=None,
        channel_logo_id=None,
        m3u_profile_id=None,
        debug=True,
    )
    fake = _FakeResponse(content_type, body)
    with mock.patch.object(views, "_open_upstream", return_value=fake), \
            mock.patch.object(views.ConfigHelper, "chunk_size", return_value=262144), \
            mock.patch.object(views, "close_old_connections"):
        with capture() as logs:
            response = views._stream_from_provider(**kwargs)
    return response, logs


class UpstreamPeekLoggingTests(SimpleTestCase):
    def _assert_no_leak(self, logs):
        for rec in logs.records:
            text = _text(rec)
            for secret in SECRETS + ("Error: denied",):
                self.assertNotIn(
                    secret, text, f"provider text reached the log: {text!r}"
                )

    def _find(self, logs, needle):
        found = [r for r in logs.records if needle in r.getMessage() or needle in repr(r.args)]
        self.assertTrue(found, f"diagnostic with {needle!r} never emitted: "
                        f"{[r.getMessage() for r in logs.records]}")
        return found

    def test_body_and_content_type_text_never_reach_the_log(self):
        response, logs = _run(
            "text/html; note=" + LOGIN_URL, BODY_TEXT.encode()
        )
        self.assertEqual(response.status_code, 404)
        # The events themselves were emitted, so this cannot pass vacuously.
        self._find(logs, "Timeshift cascade[")
        self._find(logs, "no TS sync")
        self._assert_no_leak(logs)

    def test_content_type_is_reduced_to_an_allowlisted_media_type(self):
        _, logs = _run("text/html; note=" + LOGIN_URL, BODY_TEXT.encode())
        cascade = self._find(logs, "Timeshift cascade[")[0]
        self.assertIn("text/html", repr(cascade.args))

    def test_unknown_content_type_is_logged_as_other(self):
        _, logs = _run(LOGIN_URL, BODY_TEXT.encode())
        cascade = self._find(logs, "Timeshift cascade[")[0]
        self.assertIn("other", repr(cascade.args))
        self._assert_no_leak(logs)

    def test_peek_is_logged_as_a_length_and_a_classification(self):
        body = BODY_TEXT.encode()
        _, logs = _run("text/plain", body)
        rec = self._find(logs, "no TS sync")[0]
        self.assertEqual(rec.args[1], len(body))
        self.assertEqual(rec.args[2], "other")

    def test_html_json_and_empty_bodies_are_classified(self):
        for body, label in (
            (b"  <html>" + LOGIN_URL.encode(), "html"),
            (b'{"error": "' + LOGIN_URL.encode() + b'"}', "json"),
            (b"#EXTM3U\n" + LOGIN_URL.encode(), "m3u"),
            (b"", "empty"),
        ):
            with self.subTest(label):
                _, logs = _run("text/plain", body)
                rec = self._find(logs, "no TS sync")[0]
                self.assertEqual(rec.args[2], label)
                self._assert_no_leak(logs)
