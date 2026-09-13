"""Pins apps/proxy/live_proxy/url_utils.py's validate_stream_url (Phase 2 PR 2b-4, kind 4).

Live code: called from views.py:479 and :501. Patches the transport
(requests.Session), never the function itself or any branch inside it --
patching the sink is how you observe; patching the logic that decides what
reaches the sink is how you blind yourself.

Every assertion below was verified against the real module (a throwaway
script under Django, since requests.Session needs an app registry) before
this file was written.
"""
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from apps.proxy.live_proxy.url_utils import validate_stream_url


class ValidateStreamUrlTests(SimpleTestCase):
    def _response(self, status, *, content_type=None, chunks=(b"x" * 1880,)):
        response = MagicMock()
        response.status_code = status
        response.headers = {"Content-Type": content_type} if content_type else {}
        response.iter_content = MagicMock(return_value=iter(chunks))
        return response

    def test_udp_rtp_and_rtsp_skip_validation_without_a_request(self):
        for url in ("udp://239.0.0.1:1234", "rtp://239.0.0.1:1234",
                    "rtsp://example.invalid/stream"):
            with self.subTest(url=url):
                with patch("apps.proxy.live_proxy.url_utils.requests.Session") as session_cls:
                    result = validate_stream_url(url)
                self.assertEqual(
                    result,
                    (True, url, 200,
                     "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"),
                )
                # Pins the EARLY RETURN, not merely a truthy result: without
                # this assertion the test would pass even if the early
                # return were deleted and the HEAD happened to succeed.
                session_cls.assert_not_called()

    def test_head_succeeds(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(200)
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            result = validate_stream_url(url)
        self.assertEqual(result, (True, url, 200, "Valid (HEAD request)"))
        session.get.assert_not_called()

    def test_head_raises_falls_back_to_get(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.side_effect = requests.exceptions.RequestException("no HEAD")
        session.get.return_value = self._response(200, content_type="video/mp2t")
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            is_valid, _, status, message = validate_stream_url(url)
        self.assertTrue(is_valid)
        self.assertEqual(status, 200)
        self.assertIn("received 1880 bytes", message)
        self.assertIn("recognized as valid stream format", message)

    def test_head_non_2xx_without_exception_falls_back_to_get(self):
        # Distinct from the exception branch above: head_request_success is
        # True here and False there.
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(200, content_type="video/mp2t")
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            validate_stream_url(url)
        session.get.assert_called_once()

    def test_get_non_2xx(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        get_response = self._response(404)
        session.get.return_value = get_response
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            result = validate_stream_url(url)
        self.assertEqual(result, (False, url, 404, "Invalid HTTP status: 404"))
        # Status is checked before content -- ordering is the assertion.
        get_response.iter_content.assert_not_called()

    def test_empty_body(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(200, chunks=())
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            is_valid, _, status, message = validate_stream_url(url)
        # The first element is False while status is 200 -- a reader who
        # only checks status sees a success.
        self.assertFalse(is_valid)
        self.assertEqual(status, 200)
        self.assertTrue(message.startswith("Empty response from server"))

    def test_content_type_recognised(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(
            200, content_type="application/vnd.apple.mpegurl"
        )
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            _, _, _, message = validate_stream_url(url)
        self.assertTrue(message.endswith(", recognized as valid stream format)"))

    def test_content_type_unrecognised_is_still_valid(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(200, content_type="text/html")
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            is_valid, _, _, message = validate_stream_url(url)
        self.assertTrue(message.endswith(", unrecognized but may still work)"))
        self.assertTrue(is_valid)

    def test_no_content_type_header_at_all(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(200, content_type=None)
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            _, _, _, message = validate_stream_url(url)
        self.assertNotIn("(Content-Type:", message)

    def test_content_type_table_is_a_substring_match(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(405)
        session.get.return_value = self._response(200, content_type="video/")
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            _, _, _, message = validate_stream_url(url)
        self.assertTrue(message.endswith(", recognized as valid stream format)"))

        # An entry of bare 'ts' matches any content type containing the
        # letters ts -- a real property of this table, not a guess.
        session.get.return_value = self._response(
            200, content_type="application/x-custom-ts"
        )
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            _, _, _, message = validate_stream_url(url)
        self.assertTrue(message.endswith(", recognized as valid stream format)"))

    def test_the_four_terminal_except_arms(self):
        url = "http://example.invalid/stream.ts"
        cases = [
            (requests.exceptions.Timeout(),
             (False, url, 0, "Timeout connecting to stream")),
            (requests.exceptions.TooManyRedirects(),
             (False, url, 0, "Too many redirects")),
            (requests.exceptions.RequestException("boom"),
             (False, url, 0, "Request error: boom")),
            (ValueError("boom"), (False, url, 0, "Validation error: boom")),
        ]
        # Timeout and TooManyRedirects are both subclasses of
        # RequestException, so the arms must stay in this order for the
        # first two to be reachable at all -- the exact messages below are
        # what proves the order held.
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                session = MagicMock()
                session.head.return_value = self._response(405)
                session.get.side_effect = exc
                with patch(
                    "apps.proxy.live_proxy.url_utils.requests.Session",
                    return_value=session,
                ):
                    result = validate_stream_url(url)
                self.assertEqual(result, expected)

    def test_session_close_called_on_success_and_on_the_value_error_path(self):
        url = "http://example.invalid/stream.ts"
        session = MagicMock()
        session.head.return_value = self._response(200)
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session
        ):
            validate_stream_url(url)
        session.close.assert_called_once()

        session2 = MagicMock()
        session2.head.return_value = self._response(405)
        session2.get.side_effect = ValueError("boom")
        with patch(
            "apps.proxy.live_proxy.url_utils.requests.Session", return_value=session2
        ):
            validate_stream_url(url)
        session2.close.assert_called_once()
