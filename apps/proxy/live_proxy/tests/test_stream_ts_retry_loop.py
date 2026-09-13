"""stream_ts's connection-retry loop (Phase 2 PR 2b-4, Task 8b, promoted from
Task 12's reserve per the band-381-400 decision rule).

The owner-init path's fixed-interval retry loop around generate_stream_url():
the "insufficient time for another sleep cycle" break, the sleep-and-back-off
continuation, the final attempt at the timeout boundary, and
control_plane.release_source() on the abandoned slot when that final attempt
also fails. Fixture copied from test_stream_ts_client_registration.py's
_channel/_active_proxy_server/_request, per that file's own stated
convention (each test module keeps its own rather than sharing one).

`apps.proxy.live_proxy.views.time` IS the real global `time` module (views.py
just does `import time`), so patching `...views.time.time` patches
`time.time` for the WHOLE PROCESS, not just this module -- and several other
tests in this suite construct a real ProxyServer(), whose cleanup thread and
event listener are permanent background threads with no stop mechanism
(server.py's own docstrings note this). Under a full-package run those
threads can still be alive and calling time.time() concurrently, so a bare
finite `side_effect` list is fragile: a single stray call from an unrelated
leaked thread exhausts it early and turns a controlled scenario into a
StopIteration deep inside the view (observed as a 500 in CI-style full-suite
runs; every test here passed reliably in file-level isolation, which is what
exposed this). `_resilient_time_sequence` pads the tail with the last
scripted value instead of raising, which is enough to keep the specific
sequence traced against the function's own call sites correct against any
plausible amount of stray background noise.
"""
from unittest.mock import MagicMock, call, patch

from django.test import RequestFactory, SimpleTestCase
from django.http import StreamingHttpResponse


def _resilient_time_sequence(values):
    """A time.time() side_effect that repeats its last value once exhausted,
    rather than raising StopIteration on an unexpected extra call."""
    state = {"i": 0}

    def _next():
        i = state["i"]
        state["i"] += 1
        return values[i] if i < len(values) else values[-1]

    return _next


def _decision(user=None, client_id="client_test_1", channel_uuid=""):
    from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_LIVE,
        channel_uuid=channel_uuid,
        client_id=client_id,
        user_id=str(user.id) if user is not None else "",
        relay_name="py",
        user=user,
    )


class StreamTsRetryLoopTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def _channel(self):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        channel.name = "Test Channel"
        stream_profile = MagicMock()
        stream_profile.is_redirect.return_value = False
        channel.get_stream_profile.return_value = stream_profile
        return channel

    def _owner_init_proxy_server(self):
        client_manager = MagicMock()
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.get.return_value = None
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: client_manager}
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.am_i_owner.return_value = True
        proxy_server.ensure_output_profile.return_value = True
        proxy_server.try_acquire_ownership.return_value = True
        proxy_server._channels_setting_up = set()
        import gevent.lock
        lock = gevent.lock.RLock()
        proxy_server._get_channel_init_lock.return_value = lock
        proxy_server._finish_channel_init_lock.side_effect = (
            lambda _cid, held: held.release()
        )
        proxy_server._clear_channel_setting_up.side_effect = (
            lambda cid: proxy_server._channels_setting_up.discard(cid)
        )
        return proxy_server, client_manager

    def _request(self):
        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")
        request.user = MagicMock(is_authenticated=False)
        return request

    def _fail_tuple(self, *, error_reason=None, slot_reserved=False):
        return (None, None, False, None, slot_reserved, error_reason,
                {"channel_name": None, "stream_name": None,
                 "m3u_profile_name": None, "ffmpeg_stream_profile": None})

    def _success_tuple(self):
        return ("http://example/stream", "ua", False, "None", True, None,
                {"channel_name": None, "stream_name": None,
                 "m3u_profile_name": None, "ffmpeg_stream_profile": None})

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views.gevent.sleep")
    @patch("apps.proxy.live_proxy.views.time.time")
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
    def test_a_retryable_failure_sleeps_and_succeeds_on_the_next_attempt(
        self, mock_proxy_cls, _authorize, mock_get_stream_object, _unavailable,
        _output_profile, _output_format, _init_channel, mock_generate, mock_time,
        mock_sleep, mock_create_generator, _mock_close,
    ):
        # Iteration 1 fails with no error_reason (retryable, not the "not
        # related to connection limits" break); elapsed time stays small, so
        # the loop takes the sleep-and-continue path, not the
        # insufficient-time break. Iteration 2 succeeds.
        mock_generate.side_effect = [self._fail_tuple(), self._success_tuple()]
        mock_time.side_effect = _resilient_time_sequence([0.0, 0.1, 0.15, 0.2])

        proxy_server, client_manager = self._owner_init_proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(mock_generate.call_count, 2)
        # `apps.proxy.live_proxy.views.gevent` IS the real global gevent
        # module (views.py just does `import gevent`), so this patch is
        # process-wide -- an unrelated leaked background greenlet elsewhere
        # in the suite calls gevent.sleep(1) at a high rate under a
        # full-package run (observed: 1157 stray calls in one run), which a
        # bare assert_called_once() cannot tell apart from this test's own
        # single call. Counting calls with retry_interval's specific first
        # value (0.1) is what survives that noise.
        self.assertEqual(mock_sleep.call_args_list.count(call(0.1)), 1)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views.gevent.sleep")
    @patch("apps.proxy.live_proxy.views.time.time")
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
    def test_insufficient_time_breaks_early_and_the_final_attempt_succeeds(
        self, mock_proxy_cls, _authorize, mock_get_stream_object, _unavailable,
        _output_profile, _output_format, _init_channel, mock_generate, mock_time,
        mock_sleep, mock_create_generator, _mock_close,
    ):
        # Iteration 1 fails; elapsed jumps straight to 2.95s out of a 3s
        # budget, so remaining_time (0.05s) <= retry_interval (0.1s) --
        # the "insufficient time for another sleep cycle" break, not the
        # sleep path. The final attempt (made once, at the timeout
        # boundary) then succeeds.
        mock_generate.side_effect = [self._fail_tuple(), self._success_tuple()]
        mock_time.side_effect = _resilient_time_sequence([0.0, 0.1, 2.95, 2.96])

        proxy_server, client_manager = self._owner_init_proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        response = stream_ts(self._request(), self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertEqual(mock_generate.call_count, 2)
        # The break took the early exit -- no sleep was attempted between
        # the single loop iteration and the final attempt. Checked against
        # retry_interval's specific value rather than a bare
        # assert_not_called(), for the same stray-background-greenlet reason
        # documented at the top of this file (that mock is process-wide).
        self.assertNotIn(call(0.1), mock_sleep.call_args_list)

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.control_plane.release_source")
    @patch("apps.proxy.live_proxy.views.gevent.sleep")
    @patch("apps.proxy.live_proxy.views.time.time")
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
    def test_a_reserved_slot_is_released_when_the_final_attempt_also_fails(
        self, mock_proxy_cls, _authorize, mock_get_stream_object, _unavailable,
        _output_profile, _output_format, _init_channel, mock_generate, mock_time,
        mock_sleep, mock_release_source, mock_create_generator, _mock_close,
    ):
        from apps.proxy import control_plane

        # Both attempts fail; the second carries slot_reserved=True, so the
        # abandoned slot must be released. release_source is made to RAISE
        # the caught exception (rather than just returning False) because
        # that is the arm this test exists to reach -- the plain "returns
        # False" path is already covered elsewhere.
        mock_generate.side_effect = [
            self._fail_tuple(),
            self._fail_tuple(slot_reserved=True),
        ]
        mock_time.side_effect = _resilient_time_sequence([0.0, 0.1, 2.95, 2.96])
        mock_release_source.side_effect = control_plane.ControlPlaneRefused(
            403, "/api/relay/channels/channel-uuid/release"
        )

        proxy_server, client_manager = self._owner_init_proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server
        mock_get_stream_object.return_value = self._channel()
        mock_create_generator.return_value = lambda: iter([b"chunk"])

        from apps.proxy.live_proxy.views import stream_ts

        with self.assertLogs("live_proxy", level="WARNING") as logs:
            response = stream_ts(self._request(), self.channel_id)

        mock_release_source.assert_called_once_with(self.channel_id)
        self.assertTrue(
            any("Could not release the slot" in line for line in logs.output)
        )
        # The view still answers (an error JsonResponse, not a 500) even
        # though the cleanup attempt itself failed.
        self.assertFalse(isinstance(response, StreamingHttpResponse))
