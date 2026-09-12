"""The relay's control-plane client (Phase 1 PR 6, D9).

requests.request is patched throughout: these tests exercise the retry,
timeout, header and error-mapping behaviour of apps.proxy.control_plane,
never a real network call.
"""

import json
import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.proxy import control_plane, internal_base_url
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    internal_principal_token,
    request_is_internal_request,
)

# Sentinel distinguishing "no body given" (defaults to {}) from an explicit
# json_body=None, which is itself one of the malformed-2xx shapes tested
# below — a plain `json_body=None` default couldn't tell those apart.
_UNSET = object()


def _response(status_code=200, json_body=_UNSET, json_error=None):
    response = mock.Mock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {} if json_body is _UNSET else json_body
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


class HostValidationTests(SimpleTestCase):
    """The Host header Django would refuse must never leave the relay.

    Task 14 found this the hard way: docker/tests/test-puid-pgid.sh's
    role_split scenario named its API container "puid_test_role_api" and
    the modular branch built that verbatim into a Host header, which
    Django's get_host() rejects before ALLOWED_HOSTS is even consulted
    (host_validation_re excludes underscores) -- a bare 400 with nothing
    in the API log pointing at the real cause.
    """

    def setUp(self):
        internal_base_url._host_validation_warned = False
        self.addCleanup(setattr, internal_base_url, "_host_validation_warned", False)

    def test_an_underscored_web_host_is_rejected_loudly(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "puid_test_role_api"},
            clear=False,
        ):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            with self.assertRaises(ImproperlyConfigured) as ctx:
                control_plane.get_control_plane_base_url()
        message = str(ctx.exception)
        self.assertIn("DISPATCHARR_WEB_HOST", message)
        self.assertIn("puid_test_role_api", message)

    def test_a_hyphenated_web_host_is_accepted(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "puid-test-role-api"},
            clear=False,
        ):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            os.environ.pop("DISPATCHARR_PORT", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(),
                "http://puid-test-role-api:9191",
            )

    def test_an_underscored_explicit_base_url_is_rejected_loudly(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://bad_host:9191"},
            clear=False,
        ):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                control_plane.get_control_plane_base_url()
        self.assertIn("DISPATCHARR_INTERNAL_API_BASE_URL", str(ctx.exception))

    def test_an_ipv6_explicit_base_url_is_accepted_unchanged(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://[::1]:9191/"},
            clear=False,
        ):
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://[::1]:9191"
            )

    def test_an_ipv4_explicit_base_url_is_accepted_unchanged(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://10.0.0.5:9191/"},
            clear=False,
        ):
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://10.0.0.5:9191"
            )

    def test_userinfo_in_an_explicit_base_url_is_accepted_unchanged(self):
        # requests turns "user:pw@host" into HTTP Basic auth and sends
        # "Host: host:9191" on the wire -- Django would accept this Host,
        # so validating the raw netloc (userinfo included) must not reject
        # a URL that is actually fine.
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://user:pw@web:9191/"},
            clear=False,
        ):
            self.assertEqual(
                control_plane.get_control_plane_base_url(),
                "http://user:pw@web:9191",
            )

    def test_userinfo_never_reaches_the_rejection_message_or_log(self):
        # A bad host with credentials attached must still be rejected (the
        # host, not the userinfo, is the problem here), but the password
        # must not ride along into the exception text or the ERROR log --
        # both can end up in an anonymous streaming client's response body
        # by the time this reaches stream_ts's catch-all.
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://user:pw@bad_host:9191"},
            clear=False,
        ):
            with self.assertLogs("apps.proxy.internal_base_url", level="ERROR") as logs:
                with self.assertRaises(ImproperlyConfigured) as ctx:
                    control_plane.get_control_plane_base_url()
        self.assertIn("DISPATCHARR_INTERNAL_API_BASE_URL", str(ctx.exception))
        self.assertNotIn("pw", str(ctx.exception))
        for line in logs.output:
            self.assertNotIn("pw", line)

    def test_a_scheme_less_explicit_base_url_is_rejected_with_its_own_message(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "web:9191"},
            clear=False,
        ):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                control_plane.get_control_plane_base_url()
        message = str(ctx.exception)
        self.assertIn("DISPATCHARR_INTERNAL_API_BASE_URL", message)
        self.assertIn("http(s)", message)
        self.assertNotIn("hyphens", message)

    def test_a_scheme_less_url_with_userinfo_never_echoes_the_password(self):
        # An operator who forgot "http://": urlsplit takes "user" as the
        # scheme and "pw@web:9191" as the path, so there is no netloc to
        # redact at all. The scheme-check message must therefore name only
        # the variable, never any form of the value.
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "user:pw@web:9191"},
            clear=False,
        ):
            with self.assertLogs("apps.proxy.internal_base_url", level="ERROR") as logs:
                with self.assertRaises(ImproperlyConfigured) as ctx:
                    control_plane.get_control_plane_base_url()
        self.assertIn("DISPATCHARR_INTERNAL_API_BASE_URL", str(ctx.exception))
        self.assertNotIn("pw", str(ctx.exception))
        for line in logs.output:
            self.assertNotIn("pw", line)

    def test_a_bad_modular_host_with_userinfo_never_echoes_the_password(self):
        # DISPATCHARR_WEB_HOST=user:pw@web is a working configuration
        # (requests turns it into basic auth) -- not hypothetical -- so a
        # bad host with userinfo attached must still be rejected without
        # leaking the password, the same as the explicit-URL case.
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "user:pw@bad_host"},
            clear=False,
        ):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            with self.assertLogs("apps.proxy.internal_base_url", level="ERROR") as logs:
                with self.assertRaises(ImproperlyConfigured) as ctx:
                    control_plane.get_control_plane_base_url()
        self.assertIn("DISPATCHARR_WEB_HOST", str(ctx.exception))
        self.assertNotIn("pw", str(ctx.exception))
        for line in logs.output:
            self.assertNotIn("pw", line)

    def test_a_good_modular_host_with_userinfo_is_accepted(self):
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "user:pw@web"},
            clear=False,
        ):
            os.environ.pop("DISPATCHARR_INTERNAL_API_BASE_URL", None)
            os.environ.pop("DISPATCHARR_PORT", None)
            self.assertEqual(
                control_plane.get_control_plane_base_url(),
                "http://user:pw@web:9191",
            )

    def test_an_unparseable_url_raises_improperly_configured_not_value_error(self):
        # urlsplit() itself raises a bare ValueError on an unbalanced IPv6
        # bracket -- must be caught and turned into the same exception
        # type every other rejection uses, or it escapes release_source()
        # and post_events() (neither catches ValueError) and aborts
        # exactly the teardown/event paths this whole fix wave protects.
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://[::1:9191"},
            clear=False,
        ):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                control_plane.get_control_plane_base_url()
        self.assertIn("DISPATCHARR_INTERNAL_API_BASE_URL", str(ctx.exception))


@override_settings(SECRET_KEY="control-plane-test-secret")
class _ControlPlaneTestCase(SimpleTestCase):
    """Shared fixture: requests.request and time.sleep mocked, with the
    real exception classes attached so tests can raise genuine instances.
    """

    def setUp(self):
        patcher = mock.patch.object(control_plane, "requests")
        self.requests = patcher.start()
        self.addCleanup(patcher.stop)

        import requests as real_requests

        self.requests.RequestException = real_requests.RequestException
        self.requests.ConnectionError = real_requests.ConnectionError
        self.requests.ReadTimeout = real_requests.ReadTimeout

        sleep_patcher = mock.patch.object(control_plane.time, "sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

        # post_events' outage-suppression flag (module-level, process-wide)
        # must not leak between tests regardless of run order.
        control_plane._events_down = False
        self.addCleanup(setattr, control_plane, "_events_down", False)


class PostTransportTests(_ControlPlaneTestCase):
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

    def test_a_redirect_is_never_followed(self):
        self.requests.request.return_value = _response(200, {})

        control_plane._post("/api/relay/events", {"events": []})

        _, kwargs = self.requests.request.call_args
        self.assertIs(kwargs["allow_redirects"], False)

    def test_a_redirect_is_not_followed_and_is_an_outage(self):
        # allow_redirects=False means requests hands the 3xx straight
        # back instead of following it; the internal token must never
        # travel to wherever Location points, so this must not be treated
        # as an answer.
        self.requests.request.return_value = _response(302)

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane._post("/api/relay/events", {"events": []})

        self.assertEqual(self.requests.request.call_count, 1)

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

    def test_a_read_timeout_is_retried_then_raises_unavailable(self):
        # The mapping the failover loop depends on most: a stalled read
        # from Django, not just a refused connection.
        self.requests.request.side_effect = self.requests.ReadTimeout("slow")

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

    def test_a_2xx_with_a_non_object_json_body_is_an_outage(self):
        # A 2xx whose JSON parses fine but isn't a dict -- a list, a bare
        # string, or a JSON null -- is exactly the shape that would
        # otherwise let `answer.get(...)` raise AttributeError out of a
        # greenlet instead of being a catchable outage.
        for body in ([], None, "a string"):
            with self.subTest(body=body):
                self.requests.request.return_value = _response(200, body)
                with self.assertRaises(control_plane.ControlPlaneUnavailable):
                    control_plane._post("/api/relay/events", {"events": []})


class NextSourceTests(_ControlPlaneTestCase):
    def test_next_source_posts_to_the_channel_path_with_the_default_payload(self):
        self.requests.request.return_value = _response(
            200, {"source": None, "alternates": [], "error": None}
        )

        control_plane.next_source("some-uuid")

        args, kwargs = self.requests.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(
            args[1],
            control_plane.get_control_plane_base_url()
            + "/api/relay/channels/some-uuid/next-source",
        )
        body = json.loads(kwargs["data"])
        self.assertEqual(body, {"exclude_stream_ids": [], "reason": "initial"})

    def test_next_source_posts_every_optional_field_when_given(self):
        self.requests.request.return_value = _response(
            200, {"source": None, "alternates": [], "error": None}
        )

        control_plane.next_source(
            "some-uuid",
            exclude_stream_ids=[1, 2],
            current_url="http://example.com/a.ts",
            target_stream_id=5,
            current_stream_id=3,
            reason="failover",
            include_alternates=True,
        )

        _, kwargs = self.requests.request.call_args
        body = json.loads(kwargs["data"])
        self.assertEqual(
            body,
            {
                "exclude_stream_ids": [1, 2],
                "reason": "failover",
                "current_url": "http://example.com/a.ts",
                "target_stream_id": 5,
                "current_stream_id": 3,
                "include_alternates": True,
            },
        )

    def test_a_404_is_no_source_not_an_outage(self):
        # The channel-deleted-mid-playback case: get_alternate_streams
        # answers this today by catching Http404 and letting
        # _try_next_stream return False. next_source() must not raise.
        self.requests.request.return_value = _response(404)

        answer = control_plane.next_source("some-uuid")

        self.assertEqual(
            answer,
            {
                "source": None,
                "alternates": [],
                "error": "identifier not found",
                # 2b-2: shape-complete so a caller can index it unconditionally.
                "output_profiles": {},
            },
        )

    def test_a_non_404_refusal_propagates(self):
        self.requests.request.return_value = _response(403)

        with self.assertRaises(control_plane.ControlPlaneRefused):
            control_plane.next_source("some-uuid")

    def test_next_source_rejects_a_non_dict_source(self):
        self.requests.request.return_value = _response(
            200, {"source": "not-a-dict", "alternates": [], "error": None}
        )

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane.next_source("some-uuid")

    def test_next_source_rejects_non_list_alternates(self):
        self.requests.request.return_value = _response(
            200, {"source": None, "alternates": "not-a-list", "error": None}
        )

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane.next_source("some-uuid")

    def test_next_source_with_a_bad_host_raises_improperly_configured_with_no_call(self):
        # A misconfigured host must fail before any HTTP call is attempted,
        # and as ImproperlyConfigured specifically -- never
        # ControlPlaneUnavailable, which would fire the degraded fallback
        # instead of failing loudly (see HostValidationTests).
        internal_base_url._host_validation_warned = False
        self.addCleanup(setattr, internal_base_url, "_host_validation_warned", False)
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://bad_host:9191"},
            clear=False,
        ):
            with self.assertRaises(ImproperlyConfigured):
                control_plane.next_source("some-uuid")
        self.requests.request.assert_not_called()


class ReleaseSourceTests(_ControlPlaneTestCase):
    def test_release_source_posts_the_three_ids_and_returns_released(self):
        self.requests.request.return_value = _response(200, {"released": True})

        result = control_plane.release_source(
            "some-uuid", stream_id=5, m3u_profile_id=2, channel_pk=9
        )

        self.assertTrue(result)
        args, kwargs = self.requests.request.call_args
        self.assertEqual(
            args[1],
            control_plane.get_control_plane_base_url()
            + "/api/relay/channels/some-uuid/release",
        )
        body = json.loads(kwargs["data"])
        self.assertEqual(body, {"stream_id": 5, "m3u_profile_id": 2, "channel_pk": 9})

    def test_release_source_returns_false_when_not_released(self):
        self.requests.request.return_value = _response(200, {"released": False})

        result = control_plane.release_source("some-uuid")

        self.assertFalse(result)

    def test_release_source_propagates_unavailable(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")

        with self.assertRaises(control_plane.ControlPlaneUnavailable):
            control_plane.release_source("some-uuid")

    def test_release_source_propagates_refused(self):
        # release_source does not catch either exception itself (ruling
        # 9): the call site decides whether an unreachable control plane
        # is worth a WARNING and moving on, since it already knows what
        # it was tearing down.
        self.requests.request.return_value = _response(403)

        with self.assertRaises(control_plane.ControlPlaneRefused):
            control_plane.release_source("some-uuid")

    def test_release_source_with_a_bad_host_returns_false_with_no_call(self):
        # release_source() must not raise ImproperlyConfigured -- a
        # misconfigured control plane must not abort a channel teardown,
        # only be reported as "not released" like any other failed release.
        internal_base_url._host_validation_warned = False
        self.addCleanup(setattr, internal_base_url, "_host_validation_warned", False)
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://bad_host:9191"},
            clear=False,
        ):
            released = control_plane.release_source("some-uuid")
        self.assertFalse(released)
        self.requests.request.assert_not_called()


class EmitEventTests(_ControlPlaneTestCase):
    def test_emit_event_never_raises_when_the_control_plane_is_down(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")

        with self.assertLogs("apps.proxy.control_plane", "WARNING"):
            result = control_plane.emit_event("channel_start", channel_id="x")

        self.assertIsNone(result)

    def test_emit_event_never_raises_with_a_bad_host(self):
        # post_events()'s own docstring says "Never raises" -- it must
        # catch ImproperlyConfigured too, or a misconfigured host either
        # propagates out of a Celery worker's synchronous _spawn call, or
        # (on a gevent greenlet) prints an unhandled-exception traceback
        # per event instead of a one-line log.
        internal_base_url._host_validation_warned = False
        self.addCleanup(setattr, internal_base_url, "_host_validation_warned", False)
        with mock.patch.dict(
            os.environ,
            {"DISPATCHARR_INTERNAL_API_BASE_URL": "http://bad_host:9191"},
            clear=False,
        ):
            with self.assertLogs("apps.proxy.control_plane", "ERROR"):
                result = control_plane.emit_event("channel_start", channel_id="x")

        self.assertIsNone(result)
        self.requests.request.assert_not_called()

    def test_emit_event_never_raises_on_a_refusal(self):
        # _spawn is synchronous in the test environment (no gevent hub, not
        # a Celery worker context), so an escaping ControlPlaneRefused would
        # surface here exactly as it would inside stop_channel.
        self.requests.request.return_value = _response(403)

        with self.assertLogs("apps.proxy.control_plane", "ERROR") as logs:
            result = control_plane.emit_event("channel_start", channel_id="x")

        self.assertIsNone(result)
        self.assertTrue(any("403" in message for message in logs.output))
        # Never the body, and never a URL -- only the status.
        self.assertFalse(any("api/relay" in message for message in logs.output))

    def test_emit_event_posts_one_batch_of_one(self):
        self.requests.request.return_value = _response(200, {"ok": True})

        control_plane.emit_event(
            "channel_start", channel_id="x", channel_name="News", foo="bar"
        )

        args, kwargs = self.requests.request.call_args
        self.assertEqual(
            args[1], control_plane.get_control_plane_base_url() + "/api/relay/events"
        )
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


class PostEventsOutageLogSuppressionTests(_ControlPlaneTestCase):
    """Task 10 review, Minor: a Django outage must log once, not per batch.

    stream_stats alone flushes every 30s per channel plus on every parsed
    codec line, so logging at WARNING/ERROR on every failed post_events
    call would flood the log for the duration of an outage.
    """

    def test_second_consecutive_outage_logs_at_debug_not_warning(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")

        with self.assertLogs("apps.proxy.control_plane", "WARNING") as first:
            control_plane.post_events([{"type": "channel_start"}])
        self.assertTrue(any("WARNING" in line for line in first.output))

        with self.assertLogs("apps.proxy.control_plane", "DEBUG") as second:
            control_plane.post_events([{"type": "channel_start"}])
        self.assertFalse(any("WARNING" in line for line in second.output))
        self.assertTrue(any("DEBUG" in line for line in second.output))

    def test_second_consecutive_refusal_logs_at_debug_not_error(self):
        self.requests.request.return_value = _response(403)

        with self.assertLogs("apps.proxy.control_plane", "ERROR") as first:
            control_plane.post_events([{"type": "channel_start"}])
        self.assertTrue(any("ERROR" in line for line in first.output))

        with self.assertLogs("apps.proxy.control_plane", "DEBUG") as second:
            control_plane.post_events([{"type": "channel_start"}])
        self.assertFalse(any("ERROR" in line for line in second.output))

    def test_recovery_after_an_outage_logs_one_info_line(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")
        control_plane.post_events([{"type": "channel_start"}])
        self.assertTrue(control_plane._events_down)

        self.requests.request.side_effect = None
        self.requests.request.return_value = _response(200, {"ok": True})

        with self.assertLogs("apps.proxy.control_plane", "INFO") as logs:
            result = control_plane.post_events([{"type": "channel_start"}])

        self.assertTrue(result)
        self.assertFalse(control_plane._events_down)
        self.assertTrue(any("reachable again" in line for line in logs.output))

    def test_a_fresh_outage_after_recovery_logs_at_warning_again(self):
        self.requests.request.side_effect = self.requests.ConnectionError("boom")
        control_plane.post_events([{"type": "channel_start"}])

        self.requests.request.side_effect = None
        self.requests.request.return_value = _response(200, {"ok": True})
        control_plane.post_events([{"type": "channel_start"}])
        self.assertFalse(control_plane._events_down)

        self.requests.request.side_effect = self.requests.ConnectionError("boom again")
        self.requests.request.return_value = None
        with self.assertLogs("apps.proxy.control_plane", "WARNING") as logs:
            control_plane.post_events([{"type": "channel_start"}])
        self.assertTrue(any("WARNING" in line for line in logs.output))
