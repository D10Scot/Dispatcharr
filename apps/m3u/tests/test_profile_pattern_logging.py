"""M3U-side twins of apps.proxy.tests.test_profile_pattern_logging.

`get_transformed_credentials` and the connection pool's fingerprint helper sit
on the path that reaches `transform_url` with a profile's raw patterns, which
in Xtream "simple" mode are `<username>/<password>`. Neither may log a pattern
or exception text at any level.
"""

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from apps.m3u import connection_pool
from apps.m3u import tasks as m3u_tasks
from apps.m3u.tasks import get_transformed_credentials
from apps.proxy.tests.test_profile_pattern_logging import (
    REPLACE,
    SEARCH,
    NoPatternInLogs,
    capture,
)


def account():
    return SimpleNamespace(
        name="acct",
        server_url="http://prov.example.com",
        username="olduser",
        password="oldpass",
    )


def profile(search=SEARCH, replace=REPLACE):
    return SimpleNamespace(
        name="prof", pk=7, search_pattern=search, replace_pattern=replace,
        m3u_account=None,
    )


class GetTransformedCredentialsPatternLoggingTests(NoPatternInLogs, SimpleTestCase):
    def test_match_logs_no_pattern(self):
        with capture(m3u_tasks.logger) as logs:
            out = get_transformed_credentials(account(), profile())
        self.assertEqual(out[0], "http://prov.example.com")
        self.assert_no_leak(logs)

    def test_no_match_logs_no_pattern(self):
        with capture(m3u_tasks.logger) as logs:
            out = get_transformed_credentials(account(), profile("zz/zz"))
        self.assertEqual(out, ("http://prov.example.com", "olduser", "oldpass"))
        self.assert_no_leak(logs)

    def test_malformed_pattern_logs_no_pattern(self):
        with capture(m3u_tasks.logger) as logs:
            out = get_transformed_credentials(account(), profile("olduser/(oldpass"))
        self.assertEqual(out, ("http://prov.example.com", "olduser", "oldpass"))
        self.assert_no_leak(logs)

    def test_error_logs_type_only_not_exception_text(self):
        err = ValueError("bad group name 'olduser/oldpass' at position 4")
        with mock.patch("apps.m3u.tasks.regex.sub", side_effect=err):
            with capture(m3u_tasks.logger) as logs:
                out = get_transformed_credentials(account(), profile())
        self.assertEqual(out, ("http://prov.example.com", "olduser", "oldpass"))
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))


    def test_primary_profile_lookup_failure_logs_type_only(self):
        # profile=None sends the helper through the primary-profile lookup;
        # a failing lookup must log the exception type, not its text.
        err = ValueError("lookup failed near 'olduser/oldpass'")
        with mock.patch("apps.m3u.models.M3UAccountProfile.objects") as objs:
            objs.filter.side_effect = err
            with capture(m3u_tasks.logger) as logs:
                out = get_transformed_credentials(account(), None)
        self.assertEqual(out, ("http://prov.example.com", "olduser", "oldpass"))
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))


class FingerprintHelperPatternLoggingTests(NoPatternInLogs, SimpleTestCase):
    def test_fingerprint_failure_logs_type_only(self):
        sample = "http://prov.example.com/live/olduser/oldpass/1.ts"
        err = ValueError("bad group name 'olduser/oldpass' at position 4")
        with mock.patch("apps.channels.models.Stream.objects") as objs, mock.patch(
            "apps.proxy.next_source.transform_url", side_effect=err
        ):
            objs.filter.return_value.exclude.return_value.values_list.return_value.first.return_value = sample
            with capture(connection_pool.logger) as logs:
                out = connection_pool._fingerprint_from_profile_stream_url(profile())
        self.assertIsNone(out)
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))
