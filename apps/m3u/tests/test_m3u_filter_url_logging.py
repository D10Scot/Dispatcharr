"""A stream's provider URL must not reach the M3U filter and batch logs raw.

THE DEFECT. `_stream_passes_m3u_filters` logged, at DEBUG, the raw stream URL
of every stream that matched an M3U filter. Xtream-style provider URLs carry
the login in the path (`/live/<user>/<pass>/<id>.ts`) or the query string, so
a DEBUG log carried provider credentials. `process_m3u_batch_direct` had two
more of the same: a TRACE line naming the URL, and an ERROR line dumping the
whole stream record, URL included, when processing it failed.

These tests call the real functions with a credential-bearing URL, capture
every record, and fail naming the leaked value.
"""

import contextlib
import logging
from types import SimpleNamespace
from unittest import mock

import django.db
import regex
from django.test import SimpleTestCase, TestCase

from apps.m3u import tasks as m3u_tasks
from apps.m3u.utils import _BoundedFilterPattern
from apps.proxy.tests.test_profile_pattern_logging import capture, record_text

URL = "http://prov.example.com/live/olduser/oldpass/1.ts"
SECRETS = ("olduser", "oldpass")


def compiled(filter_type, pattern, exclude):
    obj = SimpleNamespace(
        filter_type=filter_type, regex_pattern=pattern, exclude=exclude,
        custom_properties={},
    )
    return [(_BoundedFilterPattern(regex.compile(pattern)), obj)]


def assert_no_secret(test, records):
    for rec in records:
        text = record_text(rec)
        for secret in SECRETS:
            test.assertNotIn(
                secret, text, f"{rec.name} {rec.levelname} leaked {secret!r}: {text}"
            )


class FilterMatchLoggingTests(SimpleTestCase):
    CASES = (
        # (filter_type, pattern, exclude) -- each matches NAME, GROUP and URL below
        ("name", "News", False),
        ("name", "News", True),
        ("group", "Live", False),
        ("group", "Live", True),
        ("url", r"prov\.example\.com", False),
        ("url", r"prov\.example\.com", True),
    )

    def test_match_logs_no_credential_and_keeps_its_verdict(self):
        for filter_type, pattern, exclude in self.CASES:
            with self.subTest(filter_type=filter_type, exclude=exclude):
                with capture(m3u_tasks.logger) as logs:
                    passed = m3u_tasks._stream_passes_m3u_filters(
                        "BBC News", URL, "Live TV",
                        compiled(filter_type, pattern, exclude),
                    )
                self.assertEqual(passed, not exclude)
                self.assertTrue(
                    any("matches filter pattern" in r.getMessage() for r in logs.records),
                    "the match DEBUG line must still be emitted",
                )
                assert_no_secret(self, logs.records)

    def test_no_match_still_passes(self):
        with mock.patch.object(m3u_tasks.logger, "debug"):
            self.assertTrue(
                m3u_tasks._stream_passes_m3u_filters(
                    "BBC News", URL, "Live TV", compiled("name", "zzz", True)
                )
            )


class BatchLoggingTests(TestCase):
    def run_batch(self, stream_info, trace_calls=None):
        account = SimpleNamespace(account_type="STD", filters=mock.MagicMock())
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        with (
            mock.patch.object(django.db.connections, "close_all"),
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks.logger, "trace") as trace,
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.process_m3u_batch_direct(
                    1, [stream_info], {}, [], compiled_filters=[]
                )
        return logs, trace

    def test_trace_line_names_no_credential(self):
        info = {"name": "BBC News", "url": URL, "attributes": {}}
        logs, trace = self.run_batch(info)
        self.assertTrue(trace.called, "the TRACE line must still be emitted")
        for call in trace.call_args_list:
            text = repr(call)
            for secret in SECRETS:
                self.assertNotIn(secret, text, f"TRACE leaked {secret!r}: {text}")

    def test_failed_stream_error_dump_names_no_credential(self):
        # No "attributes" key: processing raises and the handler dumps the record.
        logs, _ = self.run_batch({"name": "BBC News", "url": URL})
        self.assertTrue(
            any(r.levelname == "ERROR" for r in logs.records),
            "the failure ERROR must still be emitted",
        )
        assert_no_secret(self, logs.records)
