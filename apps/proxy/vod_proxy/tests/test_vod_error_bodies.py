"""#89 — a VOD 500 body must never carry the caught exception's text.

A `requests` connection/HTTP error names the upstream URL, and an XC VOD URL
carries the provider username and password
(`/movie/<user>/<pass>/<id>.<ext>`). Three handlers answered
`f"Streaming error: {e}"` / `f"HEAD error: {e}"` with that text verbatim;
each now answers a fixed, generic body. The detail stays in the server log
(`logger.error(..., exc_info=True)`, unchanged by this fix).
"""

from unittest.mock import MagicMock, patch

import requests
from django.test import RequestFactory, SimpleTestCase

# Shaped like a real requests.ConnectionError against an XC VOD URL: the
# message embeds the provider's path, including the plaintext XC password.
_UPSTREAM_ERROR = requests.exceptions.ConnectionError(
    "HTTPConnectionPool(host='provider.example', port=80): Max retries "
    "exceeded with url: /movie/alice/s3cret-pw/501.mp4"
)


def _decision(user=None):
    """The authorize hop's answer, as stream_vod now receives it."""
    from apps.proxy.authorize import SURFACE_VOD, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_VOD,
        user_id=str(user.id) if user is not None else "",
        relay_name="py",
        user=user,
    )


class StreamVodErrorBodyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path="/proxy/vod/movie/uuid/vod_1_1/"):
        request = self.factory.get(path, HTTP_USER_AGENT="test-agent")
        request.user = MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch("apps.proxy.vod_proxy.views.resolve_authorization", return_value=_decision())
    def test_a_stream_vod_upstream_error_put_the_provider_url_in_the_500_body(
        self,
        _authorize_mock,
        mock_select,
        mock_manager_cls,
        _close,
    ):
        movie = MagicMock()
        movie.name = "Test Movie"
        profile = MagicMock()
        profile.id = 1
        profile.max_streams = 5
        mock_select.return_value = {
            "content_obj": movie,
            "m3u_account": MagicMock(name="Provider"),
            "m3u_profile": profile,
            "current_connections": 0,
            "final_stream_url": "http://provider.example/movie.mp4",
        }

        mock_manager = MagicMock()
        mock_manager.stream_content_with_session.side_effect = _UPSTREAM_ERROR
        mock_manager_cls.get_instance.return_value = mock_manager

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id="uuid",
            session_id="vod_1_1",
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b"Streaming error")
        self.assertNotIn(b"s3cret-pw", response.content)


class StreamContentWithSessionErrorBodyTests(SimpleTestCase):
    def _make_manager(self):
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        mgr = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        mgr.redis_client = None
        mgr.worker_id = "test-worker"
        return mgr

    def test_a_session_stream_error_put_the_provider_url_in_the_500_body(self):
        from apps.vod.models import Movie

        mgr = self._make_manager()
        movie = MagicMock(spec=Movie)
        movie.uuid = "uuid-1-2"
        movie.name = "Test Movie"
        request = MagicMock()

        with patch.object(
            mgr, "find_matching_idle_session", side_effect=_UPSTREAM_ERROR
        ):
            response = mgr.stream_content_with_session(
                session_id="vod_1_2",
                content_obj=movie,
                stream_url="http://provider.example/movie.mp4",
                m3u_profile=MagicMock(),
                client_ip="127.0.0.1",
                client_user_agent="test-agent",
                request=request,
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b"Streaming error")
        self.assertNotIn(b"s3cret-pw", response.content)


class HeadVodErrorBodyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_a_head_vod_error_put_the_provider_url_in_the_500_body(
        self,
        _network_ok,
        _is_redirect,
        _idle,
        mock_select,
    ):
        mock_select.side_effect = _UPSTREAM_ERROR

        request = self.factory.head(
            "/proxy/vod/movie/uuid/",
            HTTP_USER_AGENT="test-agent",
        )

        from apps.proxy.vod_proxy.views import head_vod

        response = head_vod(request, content_type="movie", content_id="uuid")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b"HEAD error")
        self.assertNotIn(b"s3cret-pw", response.content)
