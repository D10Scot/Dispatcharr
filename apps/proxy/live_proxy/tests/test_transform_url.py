"""Regression tests for URL profile regex transforms.

transform_url's implementation, its `regex` import and
URL_TRANSFORM_REGEX_TIMEOUT moved to apps/proxy/next_source.py in Phase 1
PR 6 (url_utils.transform_url is a permanent re-export of the same
function object, so the import below is unchanged); only the two mock
patch targets and the timeout constant's module moved with it.
"""

import time
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy import next_source
from apps.proxy.live_proxy.url_utils import transform_url


class TransformUrlTests(SimpleTestCase):
    def test_normal_js_backreference_rewrite(self):
        result = transform_url(
            "http://example.com/live/user/pass/1.ts",
            r"(.*)/(.*)/(.*)/(.*)$",
            r"$1/newuser/newpass/$4",
        )
        self.assertEqual(result, "http://example.com/live/newuser/newpass/1.ts")

    def test_catastrophic_search_pattern_times_out(self):
        """Alternation+star ReDoS must fall back quickly instead of hanging."""
        url = ("a" * 28) + "!"
        started = time.perf_counter()
        result = transform_url(url, r"(a|a)*$", "x")
        elapsed = time.perf_counter() - started
        # Generous multiple of the timeout avoids CI flakiness while still
        # catching a regression back to unbounded backtracking.
        self.assertLess(
            elapsed,
            next_source.URL_TRANSFORM_REGEX_TIMEOUT * 20,
            f"transform_url blocked for {elapsed:.2f}s on catastrophic regex",
        )
        self.assertEqual(result, url)

    def test_subn_receives_timeout(self):
        with patch(
            "apps.proxy.next_source.regex.subn",
            return_value=("http://example.com/b", 1),
        ) as mock_subn:
            transform_url("http://example.com/a", "a", "b")
        self.assertEqual(
            mock_subn.call_args.kwargs.get("timeout"),
            next_source.URL_TRANSFORM_REGEX_TIMEOUT,
        )

    def test_timeout_error_falls_back_to_original(self):
        with patch(
            "apps.proxy.next_source.regex.subn",
            side_effect=TimeoutError("regex timed out"),
        ):
            self.assertEqual(
                transform_url("http://example.com/a", "a", "b"),
                "http://example.com/a",
            )
