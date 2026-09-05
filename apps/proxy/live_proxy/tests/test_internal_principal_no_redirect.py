"""The relay never redirects an internal principal to a third-party provider.

Phase 1 PR 5 fix round 1 (Task 8 review, Blocking finding): ffmpeg re-sends
every ``-headers`` line to wherever a redirect points, so a Redirect-profile
channel's normal 302 would hand X-Dispatcharr-Internal to the provider — a
credential that otherwise never leaves this deployment. The DVR's own
internal-principal tune must be served through the Proxy path instead
(``apps/proxy/live_proxy/views.py``'s ``stream_ts``, immediately before the
``is_redirect()`` decision); a user or anonymous tune on the same
Redirect-profile channel must still get its 302, unchanged.
"""

from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.proxy.internal_auth import internal_principal_token


def _decision(user=None, client_id="client_test_1", channel_uuid=""):
    """The authorize hop's answer, as the views now receive it."""
    from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_LIVE,
        channel_uuid=channel_uuid,
        client_id=client_id,
        user_id=str(user.id) if user is not None else "",
        relay_name="py",
        user=user,
    )


def _configure_init_lock_mocks(proxy_server):
    """Wire MagicMock ProxyServer helpers to a real gevent RLock + setup set."""
    import gevent.lock

    lock = gevent.lock.RLock()
    proxy_server._channels_setting_up = set()
    proxy_server._get_channel_init_lock.return_value = lock
    proxy_server._finish_channel_init_lock.side_effect = (
        lambda _channel_id, held_lock: held_lock.release()
    )
    proxy_server._clear_channel_setting_up.side_effect = (
        lambda channel_id: proxy_server._channels_setting_up.discard(channel_id)
    )
    return lock


@override_settings(SECRET_KEY="internal-redirect-test-secret")
class InternalPrincipalRedirectProfileTests(SimpleTestCase):
    """Redirect-profile channel, owner path (mirrors test_ghost_session_cleanup's
    test_owner_reserves_stream_after_acquiring_ownership, the only existing
    template that drives stream_ts through a real perform_setup)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def _channel(self):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        channel.get_stream_profile.return_value.is_redirect.return_value = True
        return channel

    def _proxy_server(self):
        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        _configure_init_lock_mocks(proxy_server)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        return proxy_server

    @patch("apps.proxy.live_proxy.url_utils.validate_stream_url")
    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_internal_principal_streams_instead_of_redirecting(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
        mock_validate_stream_url,
    ):
        channel = self._channel()
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = True
        # transcode=True here, exactly as generate_stream_url computes it for
        # a real (non-Proxy) profile — the view must override it to False.
        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", True, "profile", True, None,
        )

        proxy_server = self._proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server

        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")
        request.META["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            mock_create_generator.return_value = lambda: iter([b"chunk"])
            from apps.proxy.live_proxy.views import stream_ts

            response = stream_ts(request, self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_validate_stream_url.assert_not_called()
        mock_channel_service.initialize_channel.assert_called_once()
        call_args = mock_channel_service.initialize_channel.call_args
        # (channel_id, stream_url, stream_user_agent, transcode, ...) — the
        # fourth positional argument must be forced False so the Redirect
        # profile's empty build_command() is never used to spawn ffmpeg.
        self.assertFalse(call_args[0][3])

    @patch("apps.proxy.live_proxy.url_utils.validate_stream_url")
    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_anonymous_tune_still_redirects(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
        mock_validate_stream_url,
    ):
        channel = self._channel()
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", True, "profile", True, None,
        )
        mock_validate_stream_url.return_value = (
            True, "http://provider.example/final.ts", 200, "ok",
        )

        proxy_server = self._proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server

        # No X-Dispatcharr-Internal header: an ordinary (anonymous, on this
        # AllowAny surface) tune.
        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            from apps.proxy.live_proxy.views import stream_ts

            response = stream_ts(request, self.channel_id)

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response.url, "http://provider.example/final.ts")
        mock_channel_service.initialize_channel.assert_not_called()
