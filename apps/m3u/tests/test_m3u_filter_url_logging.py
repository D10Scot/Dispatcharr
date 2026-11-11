"""Provider URLs, playlist lines and stream records must not reach the M3U
refresh logs (download, content checks, parse, filter, per-stream processing).

THE DEFECT. `_stream_passes_m3u_filters` logged, at DEBUG, the raw stream URL
of every stream that matched an M3U filter. Xtream-style provider URLs carry
the login in the path (`/live/<user>/<pass>/<id>.ts`) or the query string, so
a DEBUG log carried provider credentials. `process_m3u_batch_direct` had two
more of the same: a TRACE line naming the URL, and an ERROR line dumping the
whole stream record, URL included, when processing it failed.

Review round 1 widened the scope: `redact_url` leaves an opaque path token
(`/channel/<token>/index.m3u8`) unchanged, so the stream URL is no longer
logged at all there; the failure handler dumped the whole record (catchup
source, tvg-logo and VLC options carry logins too); the download path logged
the first lines of every playlist at INFO; the parse warnings logged
attribute values; the refresh task's TRACE line dumped every parsed record.

These tests call the real functions with credential-bearing input, capture
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
OPAQUE_URL = "https://prov.example.com/channel/opaquetoken123/index.m3u8"
SERVER_URL = "http://prov.example.com/get.php?username=srvuser&password=srvpass&type=m3u"
SECRETS = (
    "olduser", "oldpass", "opaquetoken123", "srvuser", "srvpass",
    "catchuptoken", "logotoken", "vlctoken",
)


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
        for url in (URL, OPAQUE_URL):
            for filter_type, pattern, exclude in self.CASES:
                with self.subTest(url=url, filter_type=filter_type, exclude=exclude):
                    with capture(m3u_tasks.logger) as logs:
                        passed = m3u_tasks._stream_passes_m3u_filters(
                            "BBC News", url, "Live TV",
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


SECRET_RECORD = {
    "name": 12345,  # truthy, non-string: the name-length check raises
    "url": URL,
    "attributes": {
        "catchup-source": "http://prov.example.com/catchup/olduser/oldpass/catchuptoken",
        "tvg-logo": "http://prov.example.com/logo/logotoken.png?password=oldpass",
        "group-title": "Live",
    },
    "vlc_opts": ["http-referrer=http://prov.example.com/vlctoken"],
}


class BatchLoggingTests(TestCase):
    def run_batch(self, stream_info, groups=None):
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
                    1, [stream_info], groups or {}, [],
                    compiled_filters=compiled("name", "News", False),
                )
        return logs, trace

    def test_trace_line_names_no_credential(self):
        for url in (URL, OPAQUE_URL):
            with self.subTest(url=url):
                info = {"name": "BBC News", "url": url, "attributes": {}}
                logs, trace = self.run_batch(info)
                self.assertTrue(trace.called, "the TRACE line must still be emitted")
                for call in trace.call_args_list:
                    text = repr(call)
                    for secret in SECRETS:
                        self.assertNotIn(secret, text, f"TRACE leaked {secret!r}: {text}")

    def test_failed_stream_error_logs_no_record_content(self):
        logs, _ = self.run_batch(dict(SECRET_RECORD), groups={"Live": 1})
        errors = [r for r in logs.records if r.levelname == "ERROR"]
        self.assertTrue(errors, "the failure ERROR must still be emitted")
        self.assertTrue(
            any("TypeError" in r.getMessage() for r in errors),
            "the failure must name the exception type",
        )
        assert_no_secret(self, logs.records)

    def test_failed_stream_exception_text_is_not_logged(self):
        # The exception text can quote any field (here a URL-bearing name).
        info = {"name": "BBC News", "url": URL, "attributes": {}}
        boom = ValueError("bad value http://prov.example.com/live/olduser/oldpass/1.ts")
        with mock.patch.object(m3u_tasks, "get_case_insensitive_attr", side_effect=boom):
            logs, _ = self.run_batch(info)
        self.assertTrue(any(r.levelname == "ERROR" for r in logs.records))
        assert_no_secret(self, logs.records)


class ParseWarningLoggingTests(SimpleTestCase):
    EXTINF = (
        '#EXTINF:-1 catchup-source="http://prov.example.com/catchup/olduser/oldpass/catchuptoken" '
        'tvg-logo="http://prov.example.com/logo/logotoken.png",Chan'
    )

    def test_extinf_without_url_warns_without_attribute_values(self):
        lines = [self.EXTINF, "#EXTINF:-1,Next", "http://prov.example.com/next.ts"]
        with capture(m3u_tasks.logger) as logs:
            entries = list(m3u_tasks.iter_m3u_entries(lines))
        self.assertEqual(len(entries), 1)
        self.assertTrue(any(r.levelname == "WARNING" for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_trailing_extinf_without_url_warns_without_attribute_values(self):
        with capture(m3u_tasks.logger) as logs:
            self.assertEqual(list(m3u_tasks.iter_m3u_entries([self.EXTINF])), [])
        self.assertTrue(any(r.levelname == "WARNING" for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_unparseable_extinf_warns_without_line_text(self):
        bad = "#EXTINF http://prov.example.com/live/olduser/oldpass/1.ts"
        with capture(m3u_tasks.logger) as logs:
            list(m3u_tasks.iter_m3u_entries([bad, "http://prov.example.com/x.ts"]))
        self.assertTrue(any("Failed to parse #EXTINF" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)


class _Response:
    def __init__(self, status=200, body=b"", url=SERVER_URL):
        self.status_code = status
        self.headers = {"Content-Length": str(len(body))}
        self.url = url
        self._body = body

    @property
    def text(self):
        return self._body.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size=8192):
        if self._body:
            yield self._body

    def raise_for_status(self):
        pass


class FetchLoggingTests(SimpleTestCase):
    ACCOUNT_ID = 987654

    def account(self):
        return SimpleNamespace(
            id=self.ACCOUNT_ID, name="acct", server_url=SERVER_URL, file_path=None,
            status=None, last_message=None, save=mock.Mock(),
            get_user_agent_string=lambda: "UA",
        )

    def fetch(self, response=None, side_effect=None):
        account = self.account()
        path = m3u_tasks.os.path.join(m3u_tasks.m3u_dir, f"{self.ACCOUNT_ID}.m3u")
        self.addCleanup(lambda: m3u_tasks.os.path.exists(path) and m3u_tasks.os.remove(path))
        with (
            mock.patch.object(m3u_tasks.requests, "get", return_value=response, side_effect=side_effect),
            mock.patch.object(m3u_tasks, "send_m3u_update"),
        ):
            with capture(m3u_tasks.logger) as logs:
                result = m3u_tasks.fetch_m3u_lines(account, use_cache=False)
        return account, result, logs

    def test_playlist_preview_logs_no_lines(self):
        body = (
            b"#EXTM3U\n#EXTINF:-1,Chan\nhttp://prov.example.com/live/olduser/oldpass/1.ts\n"
            b"#EXTINF:-1,Chan2\nhttps://prov.example.com/channel/opaquetoken123/index.m3u8\n"
        )
        account, result, logs = self.fetch(_Response(200, body))
        self.assertEqual(result[1], True)
        self.assertTrue(any("Content preview" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_playlist_that_looks_like_an_error_warns_without_content(self):
        body = b"#EXTM3U\n#EXTINF:-1,Error TV\nhttp://prov.example.com/live/olduser/oldpass/1.ts\n"
        _, result, logs = self.fetch(_Response(200, body))
        self.assertEqual(result[1], True)
        self.assertTrue(any("disguised as HTTP 200" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_invalid_content_logs_classification_not_content(self):
        body = b"<html>error: bad login olduser/oldpass at http://prov.example.com/live/olduser/oldpass/</html>"
        account, result, logs = self.fetch(_Response(200, body))
        self.assertEqual(result, (None, False))
        self.assertTrue(any(r.levelname == "ERROR" for r in logs.records))
        assert_no_secret(self, logs.records)
        # Persisted text is unchanged by this fix: still carries the full URL.
        self.assertIn(SERVER_URL, account.last_message)

    def test_http_error_logs_no_body_and_no_raw_url(self):
        body = b"Not found: /get.php?username=srvuser&password=srvpass olduser/oldpass"
        account, result, logs = self.fetch(_Response(404, body))
        self.assertEqual(result, (None, False))
        assert_no_secret(self, logs.records)
        self.assertIn(SERVER_URL, account.last_message)

    def test_empty_playlist_logs_no_raw_url(self):
        account, result, logs = self.fetch(_Response(200, b""))
        self.assertEqual(result, (None, False))
        self.assertTrue(any(r.levelname == "ERROR" for r in logs.records))
        assert_no_secret(self, logs.records)
        self.assertIn(SERVER_URL, account.last_message)

    def test_request_exception_logs_no_url_from_the_exception_text(self):
        exc = m3u_tasks.requests.exceptions.RequestException(
            "boom for url: /get.php?username=srvuser&password=srvpass olduser/oldpass"
        )
        account, result, logs = self.fetch(side_effect=exc)
        self.assertEqual(result, (None, False))
        self.assertTrue(any(r.levelname == "ERROR" for r in logs.records))
        assert_no_secret(self, logs.records)
        self.assertIn(SERVER_URL, account.last_message)

    def test_unexpected_exception_logs_no_url_from_the_exception_text(self):
        account, result, logs = self.fetch(
            side_effect=RuntimeError("failed http://prov.example.com/live/olduser/oldpass/1.ts")
        )
        self.assertEqual(result, (None, False))
        assert_no_secret(self, logs.records)


class RefreshResultLoggingTests(SimpleTestCase):
    RESULT = (
        [{"name": "Chan", "url": URL, "attributes": {"catchup-source": OPAQUE_URL}}],
        {"Live": {}},
    )

    def run_refresh(self, trace_side_effect=None):
        account = SimpleNamespace(
            is_active=True, custom_properties={}, filters=mock.MagicMock(),
        )
        account.filters.order_by.return_value = []
        with (
            mock.patch.object(m3u_tasks, "_get_active_m3u_account", return_value=account),
            mock.patch.object(m3u_tasks, "_set_m3u_account_status"),
            mock.patch.object(m3u_tasks, "send_m3u_update"),
            mock.patch.object(m3u_tasks, "refresh_m3u_groups", return_value=self.RESULT),
            mock.patch.object(m3u_tasks.logger, "trace", side_effect=trace_side_effect) as trace,
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks._refresh_single_m3u_account_impl(987655)
        return logs, trace

    def test_group_refresh_result_trace_logs_counts_not_records(self):
        logs, trace = self.run_refresh(trace_side_effect=RuntimeError("stop here"))
        texts = [repr(c) for c in trace.call_args_list if "refresh_m3u_groups result" in repr(c)]
        self.assertTrue(texts, "the refresh result TRACE line must still be emitted")
        for text in texts:
            for secret in SECRETS:
                self.assertNotIn(secret, text, f"TRACE leaked {secret!r}: {text}")
            self.assertIn("1 stream record(s)", text)

    def test_group_refresh_exception_logs_type_only(self):
        boom = RuntimeError("fetch failed http://prov.example.com/live/olduser/oldpass/1.ts")
        logs, _ = self.run_refresh(trace_side_effect=boom)
        self.assertTrue(any("Exception in refresh_m3u_groups" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)


class BulkAndTaskFailureLoggingTests(TestCase):
    def test_bulk_failure_logs_type_only(self):
        quoted = django.db.IntegrityError(
            "duplicate key (url)=(http://prov.example.com/live/olduser/oldpass/1.ts)"
        )
        account = SimpleNamespace(account_type="STD", filters=mock.MagicMock())
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        stream_model = mock.MagicMock()
        stream_model._meta.get_field.return_value.max_length = 255
        stream_model.generate_hash_key.return_value = "h"
        stream_model.objects.filter.return_value.select_related.return_value.only.return_value = []
        stream_model.objects.bulk_create.side_effect = quoted
        record = {"name": "BBC", "url": URL, "attributes": {"group-title": "Live"}}
        with (
            mock.patch.object(django.db.connections, "close_all"),
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "Stream", stream_model),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.process_m3u_batch_direct(1, [record], {"Live": 1}, [], compiled_filters=[])
        self.assertTrue(any("Bulk operation failed" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_task_wrapper_logs_type_and_frames_not_message(self):
        boom = RuntimeError("fetch failed http://prov.example.com/live/olduser/oldpass/1.ts")
        with (
            mock.patch.object(m3u_tasks, "acquire_task_lock", return_value=True),
            mock.patch.object(m3u_tasks, "TaskLockRenewer"),
            mock.patch.object(m3u_tasks, "_release_task_db_connection"),
            mock.patch.object(m3u_tasks, "_refresh_single_m3u_account_impl", side_effect=boom),
            mock.patch.object(m3u_tasks, "_set_m3u_account_status"),
            mock.patch.object(m3u_tasks, "_ensure_m3u_refresh_terminal_status"),
            mock.patch.object(m3u_tasks, "release_task_lock"),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.refresh_single_m3u_account(987656)
        failure = [r for r in logs.records if "refresh_single_m3u_account failed" in r.getMessage()]
        self.assertTrue(failure)
        assert_no_secret(self, logs.records)
        self.assertIn("RuntimeError", failure[0].getMessage())
