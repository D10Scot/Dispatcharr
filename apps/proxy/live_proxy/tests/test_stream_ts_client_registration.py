"""Regression tests for stream_ts client registration ordering."""

from unittest.mock import MagicMock, patch

from django.http import JsonResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase


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


def _trusted_decision(output_format="fmp4", user_id="4242"):
    """A trusted (nginx-authorized) decision: no User row, ever.

    Not imported from test_output_format_from_the_hop.py on purpose --
    two independent copies of this fixture is how the follower half of a
    fork stops resembling the owner half; each test module keeps its own.
    """
    from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_LIVE,
        channel_uuid="channel-uuid",
        client_id="client_test_1",
        user_id=user_id,
        relay_name="py",
        user=None,
        trusted=True,
        output_format=output_format,
        client_ip="203.0.113.9",
    )


class StreamTsClientRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def _channel(self, *, redirect=False):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = redirect
        channel.get_stream_profile.return_value = stream_profile
        return channel

    def _active_proxy_server(self, *, am_i_owner=False, client_manager=None):
        client_manager = client_manager or MagicMock()
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: client_manager}
        proxy_server.check_if_channel_exists.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.am_i_owner.return_value = am_i_owner
        proxy_server.ensure_output_profile.return_value = True
        proxy_server._channels_setting_up = set()
        return proxy_server, client_manager

    def _request(self):
        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")
        request.user = MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_active_channel_registers_client_before_ensure_output_profile(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        call_order = []

        def _add_client(*_args, **_kwargs):
            call_order.append("add_client")
            return 1

        def _ensure_output_profile(*_args, **_kwargs):
            call_order.append("ensure_output_profile")
            return True

        client_manager.add_client.side_effect = _add_client
        proxy_server.ensure_output_profile.side_effect = _ensure_output_profile
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(call_order, ["add_client", "ensure_output_profile"])

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_active_channel_without_client_manager_returns_503(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, _client_manager = self._active_proxy_server()
        proxy_server.client_managers = {}
        proxy_server.initialize_channel.return_value = True
        proxy_server.redis_client.hmget.return_value = (
            b"http://example/stream",
            b"stream-ua",
            b"None",
        )
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 503)
        proxy_server.ensure_output_profile.assert_not_called()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_ensure_output_profile_failure_removes_registered_client(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        proxy_server.ensure_output_profile.return_value = False
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        client_manager.add_client.assert_called_once()
        client_manager.remove_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for")
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_unhandled_exception_after_registration_removes_client(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        """A crash between pre-registration and the streaming response (e.g. a
        Redis error inside ensure_output_profile/get_buffer) must not leave a
        phantom client registered - the generic exception handler has to undo
        the earlier add_client() call."""
        profile = MagicMock()
        profile.id = 2
        profile.build_command.return_value = ["ffmpeg"]
        mock_resolve_output_profile.return_value = profile

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        proxy_server.ensure_output_profile.side_effect = RuntimeError("redis down")
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        client_manager.add_client.assert_called_once()
        client_manager.remove_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_client_manager_removed_after_registration_cleans_up(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)

        def _pop_manager_after_register(*_args, **_kwargs):
            proxy_server.client_managers.pop(self.channel_id, None)
            return 1

        client_manager.add_client.side_effect = _pop_manager_after_register
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 503)
        client_manager.remove_client.assert_not_called()
        proxy_server.redis_client.srem.assert_called_once()
        proxy_server.redis_client.delete.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService.initialize_channel", return_value=True)
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_owner_init_resolves_output_profile_once(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        mock_resolve_output_profile,
        mock_resolve_output_format,
        _mock_initialize,
        mock_generate_stream_url,
        mock_create_generator,
        _mock_close,
    ):
        mock_generate_stream_url.return_value = (
            "http://example/stream",
            "ua",
            False,
            "None",
            True,
            None,
            {"channel_name": None, "stream_name": None,
             "m3u_profile_name": None, "ffmpeg_stream_profile": None},
        )

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=True)
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.try_acquire_ownership.return_value = True
        import gevent.lock
        lock = gevent.lock.RLock()
        proxy_server._get_channel_init_lock.return_value = lock
        proxy_server._finish_channel_init_lock.side_effect = (
            lambda _cid, held: held.release()
        )
        proxy_server._clear_channel_setting_up.side_effect = (
            lambda cid: proxy_server._channels_setting_up.discard(cid)
        )
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_resolve_output_profile.assert_called_once()
        mock_resolve_output_format.assert_called_once()
        client_manager.add_client.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization", return_value=_decision())
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_existing_db_cleanup_test_still_registers_client(
        self,
        mock_proxy_cls,
        _authorize_mock,
        mock_get_stream_object,
        _unavailable,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        proxy_server, client_manager = self._active_proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        client_manager.add_client.assert_called_once()
        mock_create_generator.assert_called_once()

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization")
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_a_trusted_follower_registers_the_hops_user_id_and_format(
        self, proxy_server_cls, resolve, get_stream_object, _unavailable,
        _profile, _generator, _close,
    ):
        """views.py:712 -- the client that did NOT initialize the channel.

        4242 is not 0 and not 1: add_client's own fallback is "0", so a
        test asserting "0" or a real-looking small id could pass with the
        threading deleted.
        """
        from apps.proxy.live_proxy import views

        resolve.return_value = _trusted_decision()
        get_stream_object.return_value = self._channel()
        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True
        proxy_server_cls.get_instance.return_value = proxy_server

        views.stream_ts(self._request(), self.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(kwargs["output_format"], "fmp4")

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService.initialize_channel", return_value=True)
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization")
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_a_trusted_owner_registers_the_hops_user_id_and_format(
        self, proxy_server_cls, resolve, get_stream_object, _unavailable,
        _profile, _initialize, mock_generate_stream_url, mock_create_generator,
        _close,
    ):
        """views.py:605 -- the same assertion on the other side of the fork.

        Copies test_owner_init_resolves_output_profile_once's override
        block verbatim (redis_client.exists/get, check_if_channel_exists,
        hgetall, try_acquire_ownership, the init-lock wiring) -- that is
        the only route to the owner-init branch; _active_proxy_server's
        own defaults land on :712, not :605.
        """
        from apps.proxy.live_proxy import views

        resolve.return_value = _trusted_decision()
        get_stream_object.return_value = self._channel()
        mock_generate_stream_url.return_value = (
            "http://example/stream",
            "ua",
            False,
            "None",
            True,
            None,
            {"channel_name": None, "stream_name": None,
             "m3u_profile_name": None, "ffmpeg_stream_profile": None},
        )
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        proxy_server, client_manager = self._active_proxy_server(am_i_owner=True)
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.try_acquire_ownership.return_value = True
        import gevent.lock
        lock = gevent.lock.RLock()
        proxy_server._get_channel_init_lock.return_value = lock
        proxy_server._finish_channel_init_lock.side_effect = (
            lambda _cid, held: held.release()
        )
        proxy_server._clear_channel_setting_up.side_effect = (
            lambda cid: proxy_server._channels_setting_up.discard(cid)
        )
        client_manager.add_client.return_value = True
        proxy_server_cls.get_instance.return_value = proxy_server

        views.stream_ts(self._request(), self.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(kwargs["output_format"], "fmp4")


def _trusted_request(helper, user_id=""):
    """A real trusted request, headers only -- resolve_authorization runs unpatched.

    Review finding S1: the original TrustedTuneQueriesNoUserRowTests
    patched apps.proxy.live_proxy.views.resolve_authorization directly,
    so result_from_headers -- the function this class's docstring says
    it makes a rule -- never ran. The zero-query property was pinned
    elsewhere (SurfaceSplitPremiseTests, test_authorize_view.py) but not
    here, despite the docstring's claim. Building the real headers and
    letting resolve_authorization run for real is what makes the
    property structural rather than a property of an access pattern --
    the same distinction the 2b-2 plan's Ruling R1 draws.
    """
    from apps.proxy.internal_auth import relay_trust_token

    request = helper.factory.get(
        f"/proxy/ts/stream/{helper.channel_id}/",
        HTTP_X_DISPATCHARR_AUTHORIZED=relay_trust_token(),
        HTTP_X_RELAY_CHANNEL=helper.channel_id,
        HTTP_X_RELAY_CLIENT="client_test_1",
        HTTP_X_RELAY_USER=user_id,
        HTTP_X_RELAY_OUTPUT="",
        HTTP_X_RELAY_OUTPUT_FORMAT="fmp4",
        HTTP_X_RELAY_CLIENT_IP="203.0.113.9",
    )
    request.user = MagicMock(is_authenticated=False)
    return request


class TrustedTuneQueriesNoUserRowTests(TestCase):
    """No live tune may query the User table (2b-2, Rulings R1 and R1b).

    The output format arrives on X-Relay-Output-Format and the client
    hash is written from X-Relay-User's string, so result_from_headers
    skips the row entirely on SURFACE_LIVE/SURFACE_LIVE_XC. The VOD and
    catch-up surfaces D1 leaves in Python still resolve it eagerly and
    are unaffected. This test is what makes that a rule rather than a
    property of today's call graph -- which means resolve_authorization
    itself must run unpatched (see _trusted_request's docstring, review
    finding S1): a mocked-out decision would not exercise the guard
    result_from_headers is here to prove.
    """

    def test_no_query_touches_the_user_table_on_a_trusted_tune(self):
        from django.contrib.auth import get_user_model
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Vacuous-pass guard: a substring that matches nothing passes
        # every assertion below while proving nothing, so fail loudly if
        # AUTH_USER_MODEL ever moves. 'accounts_user' is
        # settings.AUTH_USER_MODEL = "accounts.User" (dispatcharr/
        # settings.py:357) with no db_table override.
        user_table = get_user_model()._meta.db_table
        self.assertEqual(user_table, "accounts_user")

        helper = StreamTsClientRegistrationTests("setUp")
        helper.setUp()
        proxy_server, client_manager = helper._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True
        request = _trusted_request(helper)

        with CaptureQueriesContext(connection) as captured:
            with patch("apps.proxy.live_proxy.views.ProxyServer") as proxy_server_cls, \
                 patch("apps.proxy.live_proxy.views.get_stream_object",
                       return_value=helper._channel()), \
                 patch("apps.proxy.live_proxy.views.ChannelService"
                       ".is_channel_unavailable_for_new_clients", return_value=False), \
                 patch("apps.proxy.live_proxy.views._output_profile_for",
                       return_value=None), \
                 patch("apps.proxy.live_proxy.views.create_stream_generator"), \
                 patch("apps.proxy.live_proxy.views.close_old_connections"):
                proxy_server_cls.get_instance.return_value = proxy_server
                from apps.proxy.live_proxy import views

                views.stream_ts(request, helper.channel_id)

        offenders = [q["sql"] for q in captured.captured_queries if user_table in q["sql"]]
        self.assertEqual(
            offenders,
            [],
            "a trusted tune queried the user table -- something read "
            "AuthorizeResult.user on a live surface; see Ruling R1",
        )

    def test_a_header_naming_a_deleted_user_still_registers_that_id(self):
        """Ruling R1b's decision, pinned on the one input that shows it.

        A digit X-Relay-User whose row no longer exists: today
        result_from_headers re-queries and the client hash records "0";
        after 2b-2 it records what the hop resolved. The window is one
        request (the auth_request subrequest to registration), closing it
        means re-querying, and the Go relay cannot re-query at all -- so
        the contract's meaning becomes "what the hop said" and this test
        is where that is written down rather than discovered.

        4242 is not a real row and not 0: "0" is add_client's own
        fallback, so asserting "0" here would pass under either meaning.
        """
        from django.contrib.auth import get_user_model
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.assertFalse(get_user_model().objects.filter(id=4242).exists())
        user_table = get_user_model()._meta.db_table

        helper = StreamTsClientRegistrationTests("setUp")
        helper.setUp()
        proxy_server, client_manager = helper._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True
        request = _trusted_request(helper, user_id="4242")

        with CaptureQueriesContext(connection) as captured:
            with patch("apps.proxy.live_proxy.views.ProxyServer") as proxy_server_cls, \
                 patch("apps.proxy.live_proxy.views.get_stream_object",
                       return_value=helper._channel()), \
                 patch("apps.proxy.live_proxy.views.ChannelService"
                       ".is_channel_unavailable_for_new_clients", return_value=False), \
                 patch("apps.proxy.live_proxy.views._output_profile_for",
                       return_value=None), \
                 patch("apps.proxy.live_proxy.views.create_stream_generator"), \
                 patch("apps.proxy.live_proxy.views.close_old_connections"):
                proxy_server_cls.get_instance.return_value = proxy_server
                from apps.proxy.live_proxy import views

                views.stream_ts(request, helper.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(
            [q["sql"] for q in captured.captured_queries if user_table in q["sql"]],
            [],
            "the tune re-queried to discover the user was gone -- that is "
            "the query R1 removes, and the Go relay cannot make it",
        )
