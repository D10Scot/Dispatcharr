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
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount

from apps.m3u import tasks as m3u_tasks
from apps.m3u.utils import _BoundedFilterPattern
from apps.proxy.tests.test_profile_pattern_logging import capture, record_text

URL = "http://prov.example.com/live/olduser/oldpass/1.ts"
OPAQUE_URL = "https://prov.example.com/channel/opaquetoken123/index.m3u8"
SERVER_URL = "http://prov.example.com/get.php?username=srvuser&password=srvpass&type=m3u"
SECRETS = (
    "olduser", "oldpass", "opaquetoken123", "srvuser", "srvpass",
    "catchuptoken", "logotoken", "vlctoken", "idtoken", "nametoken", "typesecret", "memberfile",
)


def compiled(filter_type, pattern, exclude):
    obj = SimpleNamespace(
        filter_type=filter_type, regex_pattern=pattern, exclude=exclude,
        custom_properties={},
    )
    return [(_BoundedFilterPattern(regex.compile(pattern)), obj)]


def assert_no_secret(test, records):
    for rec in records:
        test.assertIsNone(rec.exc_info, f"{rec.name} {rec.levelname} attached a traceback")
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
                lines = [c.args[0] % c.args[1:] for c in trace.call_args_list]
                self.assertIn("Processing stream: BBC News in group Default Group", lines)
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

    MALFORMED = '#EXTINF:-1 catchup-source=http://prov.example.com/live/olduser/oldpass/1.ts?x="v",Chan'

    def test_malformed_attribute_syntax_cannot_leak_through_a_key(self):
        # The unanchored attribute regex reads the URL itself as an attribute key.
        keys = m3u_tasks.parse_extinf_line(self.MALFORMED)["attributes"]
        self.assertTrue(any("olduser" in k for k in keys), "precondition: the URL became a key")
        with capture(m3u_tasks.logger) as logs:
            list(m3u_tasks.iter_m3u_entries([self.MALFORMED, "#EXTINF:-1,Next", "http://prov.example.com/n.ts"]))
        self.assertTrue(any("had no URL (next" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_malformed_attribute_syntax_at_end_of_file_cannot_leak_through_a_key(self):
        with capture(m3u_tasks.logger) as logs:
            list(m3u_tasks.iter_m3u_entries([self.MALFORMED]))
        self.assertTrue(any("at end of file had no URL" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_unparseable_extinf_warns_without_line_text(self):
        bad = "#EXTINF http://prov.example.com/live/olduser/oldpass/1.ts"
        with capture(m3u_tasks.logger) as logs:
            list(m3u_tasks.iter_m3u_entries([bad, "http://prov.example.com/x.ts"]))
        self.assertTrue(any("Failed to parse #EXTINF" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)


class _Response:
    def __init__(self, status=200, body=b"", url=SERVER_URL, headers=None):
        self.status_code = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(body))}
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

    def test_response_headers_are_not_dumped(self):
        headers = {
            "Content-Type": "audio/x-mpegurl; charset=http://prov.example.com/live/olduser/oldpass/1.ts",
            "Content-Length": "12",
            "Location": "https://prov.example.com/channel/opaquetoken123/index.m3u8",
            "Link": "<http://prov.example.com/live/olduser/oldpass/1.ts>; rel=next",
        }
        body = b"#EXTM3U\n#EXTINF:-1,Chan\nhttp://prov.example.com/x.ts\n"
        headers = m3u_tasks.requests.structures.CaseInsensitiveDict(headers)  # as requests returns
        _, result, logs = self.fetch(_Response(200, body, headers=headers))
        self.assertEqual(result[1], True)
        meta = [r.getMessage() for r in logs.records if "Response metadata" in r.getMessage()]
        self.assertEqual(meta, ["Response metadata: content-type=audio/x-mpegurl content-length=12"])
        self.assertEqual(m3u_tasks._safe_content_length("12 http://x/olduser"), "other")
        self.assertEqual(m3u_tasks._safe_content_type("text/http://x/olduser"), "other")
        self.assertEqual(m3u_tasks._safe_content_type("text/srvpass"), "other")
        self.assertEqual(m3u_tasks._safe_content_type("Application/X-MpegURL; charset=utf-8"), "application/x-mpegurl")
        assert_no_secret(self, logs.records)

    def test_a_content_type_that_only_looks_like_a_type_is_not_logged(self):
        headers = m3u_tasks.requests.structures.CaseInsensitiveDict(
            {"Content-Type": "text/typesecret", "Content-Length": "12"}
        )
        body = b"#EXTM3U\n#EXTINF:-1,Chan\nhttp://prov.example.com/x.ts\n"
        _, result, logs = self.fetch(_Response(200, body, headers=headers))
        self.assertEqual(result[1], True)
        meta = [r.getMessage() for r in logs.records if "Response metadata" in r.getMessage()]
        self.assertEqual(meta, ["Response metadata: content-type=other content-length=12"])
        assert_no_secret(self, logs.records)

    def test_archive_error_text_is_not_logged(self):
        account = SimpleNamespace(
            id=self.ACCOUNT_ID, name="acct", server_url=None, file_path="/data/list.zip",
            status=None, last_message=None, save=mock.Mock(),
        )
        err = m3u_tasks.zipfile.BadZipFile("bad member memberfile/olduser/oldpass.m3u")
        with (
            mock.patch.object(m3u_tasks.zipfile, "ZipFile", side_effect=err),
            mock.patch.object(m3u_tasks, "send_m3u_update"),
        ):
            with capture(m3u_tasks.logger) as logs:
                result = m3u_tasks.fetch_m3u_lines(account)
        self.assertEqual(result, (None, False))
        assert_no_secret(self, logs.records)
        self.assertTrue(any("BadZipFile" in r.getMessage() for r in logs.records))
        self.assertIn("memberfile", account.last_message, "the persisted text is unchanged")

    def test_provider_text_overlapping_the_server_url_cannot_unmask_it(self):
        # A body that is a substring of the server URL used to be replaced inside
        # the assembled message first, so the URL no longer matched and survived.
        for body in (b"http", b"prov.example.com", b"srvpass", b"username=srvuser"):
            with self.subTest(body=body):
                account, result, logs = self.fetch(_Response(404, body))
                self.assertEqual(result, (None, False))
                assert_no_secret(self, logs.records)
                self.assertIn(SERVER_URL, account.last_message)
        for text in ("http", "get.php?username=srvuser"):
            with self.subTest(exception=text):
                _, result, logs = self.fetch(side_effect=RuntimeError(text))
                self.assertEqual(result, (None, False))
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
        self.assertIsNone(failure[0].exc_info, "a traceback would print the exception message")
        self.assertIn("in refresh_single_m3u_account", failure[0].getMessage(), "frame marker")


class XcAndAutoSyncLoggingTests(SimpleTestCase):
    def run_xc_groups(self, categories):
        account = SimpleNamespace(
            id=5, account_type=m3u_tasks.M3UAccount.Types.XC, server_url=SERVER_URL,
            username="srvuser", password="srvpass", status=None, last_message=None,
            save=mock.Mock(), get_user_agent_string=lambda: "UA", custom_properties={},
        )
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.get_live_categories.return_value = categories
        with (
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "XCClient", return_value=client),
            mock.patch.object(m3u_tasks, "send_m3u_update"),
            mock.patch.object(m3u_tasks, "process_groups"),
            mock.patch.object(m3u_tasks, "_refresh_m3u_groups_locked", wraps=m3u_tasks._refresh_m3u_groups_locked),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks._refresh_m3u_groups_locked(5, False, True, None)
        return logs

    def test_category_response_is_not_dumped(self):
        cats = [{
            "category_id": "1", "category_name": "Live",
            "extra": "http://prov.example.com/live/olduser/oldpass/1.ts",
        }]
        logs = self.run_xc_groups(cats)
        self.assertTrue(any("Found 1 categories" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_url_bearing_category_id_is_not_logged(self):
        cats = [{"category_id": "http://prov.example.com/live/olduser/oldpass/idtoken", "category_name": "Live"}]
        logs = self.run_xc_groups(cats)
        assert_no_secret(self, logs.records)
        self.assertTrue(any("Adding category: Live (ID: <invalid id>)" in r.getMessage() for r in logs.records))

    def test_url_bearing_stream_id_is_not_logged(self):
        account = SimpleNamespace(
            id=5, name="acct", server_url=SERVER_URL, username="srvuser", password="srvpass",
            get_user_agent_string=lambda: "UA",
        )
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.server_url = "http://prov.example.com"
        client.username, client.password = "u", "p"
        client.get_all_live_streams.return_value = [
            {"category_id": "1", "name": "",
             "stream_id": "http://prov.example.com/live/olduser/oldpass/idtoken"},
        ]
        with (
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "XCClient", return_value=client),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.collect_xc_streams(5, {"Live": {"xc_id": "1"}})
        assert_no_secret(self, logs.records)
        self.assertTrue(any("(stream_id=<invalid id>)" in r.getMessage() for r in logs.records))

    def test_safe_id_keeps_plain_ids_only(self):
        self.assertEqual(m3u_tasks._safe_id("123"), "123")
        self.assertEqual(m3u_tasks._safe_id(45), "45")
        for bad in ("http://x/olduser", "12 34", "", "1" * 13, None):
            self.assertEqual(m3u_tasks._safe_id(bad), "<invalid id>")

    def test_unexpected_category_response_is_not_dumped(self):
        logs = self.run_xc_groups({"error": "http://prov.example.com/live/olduser/oldpass/1.ts"})
        self.assertTrue(any("Unexpected response from XC server: dict" in r.getMessage() for r in logs.records))
        assert_no_secret(self, logs.records)

    def test_auto_sync_failure_logs_type_only(self):
        boom = RuntimeError("bad http://prov.example.com/live/olduser/oldpass/1.ts")
        with mock.patch.object(m3u_tasks.M3UAccount, "objects") as objects:
            objects.select_related.return_value.get.side_effect = boom
            with capture(m3u_tasks.logger) as logs:
                result = m3u_tasks.sync_auto_channels(5)
        self.assertEqual(result["status"], "error")
        self.assertIn("olduser", result["error"], "the returned payload is unchanged")
        assert_no_secret(self, logs.records)


class RefreshAutoSyncResultLoggingTests(TransactionTestCase):
    """The refresh implementation's own auto-sync result line (not
    sync_auto_channels' handler)."""

    @mock.patch("apps.m3u.tasks.log_system_event")
    @mock.patch("apps.m3u.tasks.send_m3u_update")
    @mock.patch("apps.m3u.tasks.cleanup_stale_group_relationships")
    @mock.patch("apps.m3u.tasks.cleanup_streams", return_value=0)
    @mock.patch("apps.m3u.tasks.process_m3u_batch_direct", return_value="1 created, 0 updated")
    @mock.patch("apps.m3u.tasks.sync_auto_channels")
    @mock.patch("apps.m3u.tasks.refresh_m3u_groups")
    def test_result_line_logs_status_and_counts_only(
        self, mock_groups, mock_sync, _proc, _cs, _cg, mock_ws, _log,
    ):
        account = M3UAccount.objects.create(
            name="Auto Sync Log Account", server_url="http://example.com",
            username="user", password="pass",
            account_type=M3UAccount.Types.XC, is_active=True,
        )
        group = ChannelGroup.objects.create(name="Sports")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=account, channel_group=group, enabled=True,
            auto_channel_sync=True, auto_sync_channel_start=100,
            custom_properties={"xc_id": "123"},
        )
        mock_groups.return_value = ([], {"Sports": group.id})
        secret_error = "range exhausted for http://prov.example.com/live/olduser/oldpass/1.ts"
        mock_sync.return_value = {
            "status": "error",
            "error": secret_error,
            "channels_created": 2,
            "failed_stream_details": [
                {"stream_name": "S", "group": "G", "error": secret_error},
            ],
        }
        xc_stream = {
            "name": "ESPN", "url": "http://example.com/espn.m3u8",
            "attributes": {"group-title": "Sports", "stream_id": "1"},
        }
        with mock.patch("apps.m3u.tasks.collect_xc_streams", return_value=[xc_stream]):
            with capture(m3u_tasks.logger) as logs:
                returned = m3u_tasks._refresh_single_m3u_account_impl(account.id)

        line = [r.getMessage() for r in logs.records if "Auto channel sync result" in r.getMessage()]
        self.assertEqual(
            line,
            [f"Auto channel sync result for account {account.id}: status=error counts={{'channels_created': 2}}"],
        )
        assert_no_secret(self, logs.records)
        # Returned, persisted and WebSocket data are unchanged.
        self.assertEqual(returned, "Dispatched jobs complete.")
        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertIn(f"Auto-sync error: {secret_error}", account.last_message)
        ws = mock_ws.call_args.kwargs
        self.assertEqual(ws.get("status"), "error")
        self.assertEqual(ws.get("failed_stream_details"), mock_sync.return_value["failed_stream_details"])
        self.assertEqual(ws.get("message"), account.last_message)
        self.assertEqual(ws.get("error"), account.last_message)
        self.assertEqual(ws.get("channels_created"), 2)


class LoggableNameTests(SimpleTestCase):
    def test_ordinary_names_pass_through(self):
        for name in ("BBC News", "A&E / HD", "24/7 News", "CNN (US)", "a/b", "Sport 1 - HD"):
            with self.subTest(name=name):
                self.assertEqual(m3u_tasks._loggable_name(name), name)

    def test_url_shapes_are_withheld(self):
        for name in (
            "http://prov.example.com/x",          # contains ://
            "channel?token=nametoken",             # ? followed later by =
            "live/olduser/oldpass",                # whitespace-free run, two slashes
            "x live/nametoken/1.ts y",
        ):
            with self.subTest(name=name):
                self.assertEqual(m3u_tasks._loggable_name(name), "<withheld: URL-shaped>")

    def test_non_string_names_are_stringified(self):
        self.assertEqual(m3u_tasks._loggable_name(12345), "12345")


class GeneratedNameLoggingTests(TestCase):
    """The fallback name for an empty provider name embeds the raw stream_id."""

    def run_batch(self, records):
        account = SimpleNamespace(account_type="STD", filters=mock.MagicMock())
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        trace_lines = []
        stream_model = mock.MagicMock()
        stream_model._meta.get_field.return_value.max_length = 255
        stream_model.generate_hash_key.return_value = "h"
        stream_model.objects.filter.return_value.select_related.return_value.only.return_value = []
        with (
            mock.patch.object(django.db.connections, "close_all"),
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "Stream", stream_model),
            mock.patch.object(
                m3u_tasks.logger, "trace",
                side_effect=lambda msg, *a, **k: trace_lines.append(msg % a),
            ),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.process_m3u_batch_direct(
                    1, records, {"Live": 1}, [],
                    compiled_filters=compiled("name", "acct|News", False),
                )
        return logs, trace_lines

    def test_generated_name_reaches_no_per_stream_log_but_ordinary_names_do(self):
        generated = "acct - http://prov.example.com/live/olduser/oldpass/nametoken"
        records = [
            {"name": generated, "url": URL, "attributes": {"group-title": "Live"}},
            {"name": "BBC News", "url": URL, "attributes": {"group-title": "Live"}},
            {"name": "nametoken/a/b" + "x" * 300, "url": URL, "attributes": {"group-title": "Live"}},
            {"name": "acct - nametoken?a=b", "url": "u" * 5000, "attributes": {"group-title": "Live"}},
        ]
        logs, trace_lines = self.run_batch(records)
        everything = [record_text(r) for r in logs.records] + trace_lines
        for text in everything:
            for secret in SECRETS:
                self.assertNotIn(secret, text, f"leaked {secret!r}: {text}")
        self.assertIn("Processing stream: BBC News in group Live", trace_lines)
        self.assertIn("Processing stream: <withheld: URL-shaped> in group Live", trace_lines)
        matches = [r.getMessage() for r in logs.records if "matches filter pattern" in r.getMessage()]
        self.assertIn("Stream BBC News (group Live) matches filter pattern acct|News", matches)
        self.assertIn("Stream <withheld: URL-shaped> (group Live) matches filter pattern acct|News", matches)
        self.assertTrue(any("URL too long" in r.getMessage() for r in logs.records))
        self.assertTrue(any("name too long" in r.getMessage() for r in logs.records))

    def test_failure_error_withholds_the_generated_name(self):
        # a URL-shaped str name that makes processing fail (no attributes key)
        records = [{"name": "acct - http://prov.example.com/x/nametoken", "url": URL}]
        logs, _ = self.run_batch(records)
        errors = [r.getMessage() for r in logs.records if r.levelname == "ERROR"]
        self.assertTrue(errors)
        for text in errors:
            self.assertNotIn("nametoken", text)
        self.assertIn("Failed to process stream <withheld: URL-shaped>: KeyError", errors[0])


class LoggableNameCapTests(SimpleTestCase):
    def test_overlong_slash_only_text_is_withheld_quickly(self):
        import time
        started = time.monotonic()
        self.assertEqual(m3u_tasks._loggable_name("/" * 100_000), "<withheld: URL-shaped>")
        self.assertEqual(m3u_tasks._loggable_name("a/" * 50_000 + " "), "<withheld: URL-shaped>")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_the_cap_is_512_characters(self):
        self.assertEqual(m3u_tasks._loggable_name("a" * 512), "a" * 512)
        self.assertEqual(m3u_tasks._loggable_name("a" * 513), "<withheld: URL-shaped>")

    def test_slash_heavy_text_under_the_cap_is_linear_and_withheld(self):
        self.assertEqual(m3u_tasks._loggable_name("/" * 500), "<withheld: URL-shaped>")
        self.assertEqual(m3u_tasks._loggable_name("a / b / c / d"), "a / b / c / d")


class UntruncatedClassificationTests(TestCase):
    """The marker may sit beyond the 80- and 512-character cuts."""

    GROUPS = {"Live": 1}

    def collect(self, stream_id):
        account = SimpleNamespace(
            id=5, name="acct", server_url=SERVER_URL, username="srvuser", password="srvpass",
            get_user_agent_string=lambda: "UA",
        )
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.server_url = "http://prov.example.com"
        client.username, client.password = "u", "p"
        client.get_all_live_streams.return_value = [
            {"category_id": "1", "name": "", "stream_id": stream_id},
        ]
        with (
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "XCClient", return_value=client),
            mock.patch.object(m3u_tasks.logger, "warning"),
        ):
            return m3u_tasks.collect_xc_streams(5, {"Live": {"xc_id": "1"}})

    def batch(self, records, groups=None, fail=False, filters="acct"):
        account = SimpleNamespace(account_type="XC", filters=mock.MagicMock())
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        trace_lines = []
        stream_model = self.stream_model = mock.MagicMock()
        stream_model._meta.get_field.return_value.max_length = 255
        stream_model.generate_hash_key.return_value = "h"
        if fail:
            stream_model.generate_hash_key.side_effect = ValueError("boom")
        stream_model.objects.filter.return_value.select_related.return_value.only.return_value = []
        with (
            mock.patch.object(django.db.connections, "close_all"),
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "Stream", stream_model),
            mock.patch.object(
                m3u_tasks.logger, "trace",
                side_effect=lambda msg, *a, **k: trace_lines.append(msg % a),
            ),
        ):
            with capture(m3u_tasks.logger) as logs:
                m3u_tasks.process_m3u_batch_direct(
                    1, records, self.GROUPS if groups is None else groups, [],
                    compiled_filters=compiled("name", filters, False),
                )
        return [record_text(r) for r in logs.records] + trace_lines

    def assert_clean(self, texts):
        for text in texts:
            for secret in SECRETS:
                self.assertNotIn(secret, text, f"leaked {secret!r}: {text[:200]}")

    def test_second_slash_beyond_both_cuts_reaches_no_sink(self):
        # 80 < marker < 255 < 512, and one case beyond the 512 cap.
        for stream_id in ("nametoken/" + "x" * 300 + "/1.ts", "nametoken/" + "x" * 600 + "/1.ts"):
            for fail in (False, True):
                with self.subTest(length=len(stream_id), fail=fail):
                    records = self.collect(stream_id)
                    self.assertTrue(records[0]["name"].startswith("acct - nametoken/"))
                    texts = self.batch(records, fail=fail)
                    self.assert_clean(texts)
                    self.assertTrue(any("name too long" in t for t in texts), "the warning sink ran")
                    self.assertTrue(any("Processing stream: <withheld" in t for t in texts), "the TRACE sink ran")
                    self.assertTrue(
                        fail or any("Stream <withheld: URL-shaped> (group" in t for t in texts),
                        "the filter-match sink ran",
                    )
                    self.assertTrue(
                        not fail or any("Failed to process stream <withheld" in t for t in texts),
                        "the failure sink ran",
                    )

    def test_stored_name_is_still_truncated_and_unchanged(self):
        records = self.collect("nametoken/" + "x" * 300 + "/1.ts")
        original = records[0]["name"]
        self.assertGreater(len(original), 255)
        self.batch(records)
        self.assertEqual(records[0]["name"], original)
        self.assertEqual(
            self.stream_model.call_args.kwargs["name"], original[:255],
            "the stored name is still cut to the configured limit",
        )

    def test_disabled_group_debug_withholds_a_url_shaped_group(self):
        records = [{"name": "acct one", "url": URL, "attributes": {"group-title": "nametoken/a/b"}}]
        texts = self.batch(records)
        self.assert_clean(texts)
        self.assertTrue(any("disabled or excluded group: <withheld: URL-shaped>" in t for t in texts))

    def test_helper_is_not_called_when_the_levels_are_off(self):
        records = [{"name": "acct one", "url": URL, "attributes": {"group-title": "Live"}}]
        account = SimpleNamespace(account_type="XC", filters=mock.MagicMock())
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = account
        stream_model = mock.MagicMock()
        stream_model._meta.get_field.return_value.max_length = 255
        stream_model.generate_hash_key.return_value = "h"
        stream_model.objects.filter.return_value.select_related.return_value.only.return_value = []
        previous = m3u_tasks.logger.level
        m3u_tasks.logger.setLevel(logging.INFO)
        self.addCleanup(m3u_tasks.logger.setLevel, previous)
        with (
            mock.patch.object(django.db.connections, "close_all"),
            mock.patch.object(m3u_tasks.M3UAccount, "objects", manager),
            mock.patch.object(m3u_tasks, "Stream", stream_model),
            mock.patch.object(m3u_tasks, "_loggable_name", wraps=m3u_tasks._loggable_name) as helper,
        ):
            m3u_tasks.process_m3u_batch_direct(
                1, records, {"Live": 1}, [], compiled_filters=compiled("name", "acct", False),
            )
        helper.assert_not_called()
