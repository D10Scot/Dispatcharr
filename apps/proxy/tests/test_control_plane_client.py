"""The relay's control-plane client (Phase 1 PR 6, D9).

requests.request is patched throughout: these tests exercise the retry,
timeout, header and error-mapping behaviour of apps.proxy.control_plane,
never a real network call.
"""

import json
import os
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.proxy import control_plane
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    internal_principal_token,
    request_is_internal_request,
)


def _response(status_code=200, json_body=None, json_error=None):
    response = mock.Mock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {} if json_body is None else json_body
    return response


class BaseUrlTests(SimpleTestCase):
    def test_the_base_url_follows_the_dvr_formula(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://explicit:1234/"},
            clear=False,
        ):
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://explicit:1234"
            )

        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_ENV": "modular"},
            clear=False,
        ):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            os.environ.pop("DISPATCHARR_WEB_HOST", None)
            os.environ.pop("DISPATCHARR_PORT", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://web:9191"
            )
            with mock.patch.dict(
                os.environ,
                {"DISPATCHARR_WEB_HOST": "myweb", "DISPATCHARR_PORT": "8080"},
            ):
                self.assertEqual(
                    control_plane.get_control_plane_base_url(), "http://myweb:8080"
                )

        with mock.patch.dict(os.environ, {"DISPATCHARR_ENV": "dev"}, clear=False):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://127.0.0.1:5656"
            )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            os.environ.pop("DISPATCHARR_ENV", None)
            os.environ.pop("DISPATCHARR_PORT", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://127.0.0.1:9191"
            )

    def test_a_bare_runserver_environment_resolves_to_the_aio_default(self):
        # CLAUDE.md documents `manage.py runserver` with neither
        # DISPATCHARR_ENV nor DISPATCHARR_INTERNAL_API_BASE_URL set. That
        # falls through to the AIO branch and resolves to 127.0.0.1:9191 —
        # not the dev shape's 5656 — which is why running the server bare
        # needs DISPATCHARR_ENV=dev or an explicit override. Pinning the
        # fall-through here so the trap is recorded, not just documented.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            os.environ.pop("DISPATCHARR_ENV", None)
            os.environ.pop("DISPATCHARR_PORT", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://127.0.0.1:9191"
            )


@override_settings(SECRET_KEY="control-plane-test-secret")
class PostTransportTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(control_plane, "requests")
        self.requests = patcher.start()
        self.addCleanup(patcher.stop)
        self.requests.RequestException = Exception
        # Give the mocked module a real exception hierarchy to raise, since
        # tests below construct genuine ConnectionError instances.
        import requests as real_requests

        self.requests.RequestException = real_requests.RequestException
        self.requests.ConnectionError = real_requests.ConnectionError
        sleep_patcher = mock.patch.object(control_plane.time, "sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_both_internal_headers_are_sent(self):
        self.requests.request.return_value = _response(200, {"ok": True})

        control_plane._post("/api/relay/events", {"events": []})

        _, kwargs = self.requests.request.call_args
        headers = kwargs["headers"]
        self.assertEqual(headers[HEADER_INTERNAL], internal_principal_token())

        factory = RequestFactory()
        body = kwargs["data"]
        request = factory.post(
            "/api/relay/events", data=body, content_type="application/json"
        )
        request.META["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = headers[
            HEADER_INTERNAL_REQUEST
        ]
        self.assertTrue(request_is_internal_request(request))

    def test_the_timeout_is_two_and_five(self):
        self.requests.request.return_value = _response(200, {})

        control_plane._post("/api/relay/events", {"events": []})

        _, kwargs = self.requests.request.call_args
        self.assertEqual(kwargs["timeout"], (2, 5))

    def test_one_retry_on_a_connection_error_then_success(self):
        self.requests.request.side_effect = [
            self.requests.ConnectionError("boom"),
            _response(200, {"ok": True}),
        ]

        answer = control_plane._post("/api/relay/events", {"events": []})

        self.assertEqual(answer, {"ok": True})
        self.assertEqual(self.requests.request.call_count, 2)

    def test_two_failures_raise_control_plane_unavailable(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane._post("/api/relay/events", {"events": []})

        self.assertEqual(self.requests.request.call_count, 2)

    def test_a_500_is_retried_once_and_a_400_is_not(self):
        self.requests.request.return_value = _response(500)
        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane._post("/api/relay/events", {"events": []})
        self.assertEqual(self.requests.request.call_count, 2)

        self.requests.request.reset_mock()
        self.requests.request.return_value = _response(400)
        with self.assertRaises(control_plane.ControlPlaneRefused):
            control_plane._post("/api/relay/events", {"events": []})
        self.assertEqual(self.requests.request.call_count, 1)

    def test_a_4xx_raises_refused_not_unavailable(self):
        self.requests.request.return_value = _response(403)

        with self.assertRaises(control_plane.ControlPlaneRefused) as ctx:
            control_plane._post("/api/relay/events", {"events": []})

        self.assertEqual(ctx.exception.status, 403)
        self.assertNotIsInstance(ctx.exception, control_plane.ControlPlaneUnavailable)

    def test_a_403_is_not_retried(self):
        self.requests.request.return_value = _response(403)

        with self.assertRaises(control_plane.ControlPlaneRefused):
            control_plane._post("/api/relay/events", {"events": []})

        self.assertEqual(self.requests.request.call_count, 1)

    def test_a_2xx_with_a_non_json_body_is_an_outage(self):
        self.requests.request.return_value = _response(
            200, json_error=ValueError("not json")
        )

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane._post("/api/relay/events", {"events": []})


@override_settings(SECRET_KEY="control-plane-test-secret")
class NextSourceTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(control_plane, "requests")
        self.requests = patcher.start()
        self.addCleanup(patcher.stop)
        import requests as real_requests

        self.requests.RequestException = real_requests.RequestException
        self.requests.ConnectionError = real_requests.ConnectionError
        sleep_patcher = mock.patch.object(control_plane.time, "sleep")
        self.addCleanup(sleep_patcher.stop)
        sleep_patcher.start()

    def test_a_404_is_no_source_not_an_outage(self):
        # The channel-deleted-mid-playback case: get_alternate_streams
        # answers this today by catching Http404 and letting
        # _try_next_stream return False. next_source() must not raise.
        self.requests.request.return_value = _response(404)

        answer = control_plane.next_source("some-uuid")

        self.assertEqual(
            answer, {"source": None, "alternates": [], "error": "identifier not found"}
        )

    def test_a_non_404_refusal_propagates(self):
        self.requests.request.return_value = _response(403)

        with self.assertRaises(control_plane.ControlPlaneRefused):
            control_plane.next_source("some-uuid")


@override_settings(SECRET_KEY="control-plane-test-secret")
class EmitEventTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(control_plane, "requests")
        self.requests = patcher.start()
        self.addCleanup(patcher.stop)
        import requests as real_requests

        self.requests.RequestException = real_requests.RequestException
        self.requests.ConnectionError = real_requests.ConnectionError
        sleep_patcher = mock.patch.object(control_plane.time, "sleep")
        self.addCleanup(sleep_patcher.stop)
        sleep_patcher.start()

    def test_emit_event_never_raises_when_the_control_plane_is_down(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")

        result = control_plane.emit_event("channel_start", channel_id="x")

        self.assertIsNone(result)

    def test_emit_event_never_raises_on_a_refusal(self):
        # _spawn is synchronous in the test environment (no gevent hub, not
        # a Celery worker context), so an escaping ControlPlaneRefused would
        # surface here exactly as it would inside stop_channel.
        self.requests.request.return_value = _response(403)

        result = control_plane.emit_event("channel_start", channel_id="x")

        self.assertIsNone(result)

    def test_emit_event_posts_one_batch_of_one(self):
        self.requests.request.return_value = _response(200, {"ok": True})

        control_plane.emit_event(
            "channel_start", channel_id="x", channel_name="News", foo="bar"
        )

        _, kwargs = self.requests.request.call_args
        body = json.loads(kwargs["data"])
        self.assertEqual(
            body,
            {
                "events": [
                    {
                        "type": "channel_start",
                        "channel_id": "x",
                        "channel_name": "News",
                        "details": {"foo": "bar"},
                    }
                ]
            },
        )
