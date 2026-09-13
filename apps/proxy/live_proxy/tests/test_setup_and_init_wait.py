"""Kind 2: two pure decision functions with zero `except` lines between them
(Phase 2 PR 2b-4, Task 8).

views._channel_setup_needed and ts/generator's init-wait pair are the
cheapest non-trivial block left in the denominator -- seeded-hash decision
ladders, no Redis failure handling to speak of.
"""
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelState
from apps.proxy.live_proxy.views import _channel_setup_needed, _channel_stopping_response


class ChannelStoppingResponseTests(SimpleTestCase):
    def test_the_response_shape(self):
        response = _channel_stopping_response()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "1")
        self.assertEqual(response.content, b'{"error": "Channel is stopping, retry shortly"}')


class ChannelSetupNeededTests(SimpleTestCase):
    def _proxy(self, *, metadata=None, heartbeat_exists=False, channel_exists=False,
               redis_client=True):
        """A stand-in ProxyServer carrying one metadata hash.

        Only the four members _channel_setup_needed actually reads are
        supplied; the decision ladder itself runs unpatched. Pass
        redis_client=False to exercise the `if proxy_server.redis_client`
        false path.
        """
        proxy_server = MagicMock()
        if not redis_client:
            proxy_server.redis_client = None
        else:
            proxy_server.redis_client = MagicMock()
            proxy_server.redis_client.hgetall.return_value = metadata or {}
            proxy_server.redis_client.exists.return_value = heartbeat_exists
        proxy_server.check_if_channel_exists.return_value = channel_exists
        return proxy_server

    def test_the_six_setup_decisions(self):
        for state, expected in [
            (ChannelState.ACTIVE, (False, ChannelState.ACTIVE, False)),
            (ChannelState.INITIALIZING, (False, ChannelState.INITIALIZING, True)),
            (ChannelState.CONNECTING, (False, ChannelState.CONNECTING, True)),
            (ChannelState.STOPPING, (False, ChannelState.STOPPING, False)),
            (ChannelState.ERROR, (True, ChannelState.ERROR, False)),
            (ChannelState.STOPPED, (True, ChannelState.STOPPED, False)),
        ]:
            with self.subTest(state=state):
                proxy_server = self._proxy(metadata={"state": state})
                self.assertEqual(
                    _channel_setup_needed(proxy_server, "chan"), expected
                )

    def test_waiting_for_clients_and_buffering_do_not_wait_for_init(self):
        # In the same tuple as ACTIVE but must NOT set wait_for_init -- a
        # port that transcribes the two state tuples as one gets these two
        # rows wrong and nothing else catches it.
        for state in (ChannelState.WAITING_FOR_CLIENTS, ChannelState.BUFFERING):
            with self.subTest(state=state):
                proxy_server = self._proxy(metadata={"state": state})
                self.assertEqual(
                    _channel_setup_needed(proxy_server, "chan"),
                    (False, state, False),
                )

    def test_unknown_state_with_a_live_owner_heartbeat_needs_no_setup(self):
        proxy_server = self._proxy(
            metadata={"state": "unknown-state", "owner": "worker-1"},
            heartbeat_exists=True,
        )
        result = _channel_setup_needed(proxy_server, "chan")
        self.assertEqual(result, (False, "unknown-state", False))
        # The heartbeat key is hard-coded with no RedisKeys helper -- exactly
        # what a port gets wrong if this isn't pinned.
        proxy_server.redis_client.exists.assert_called_once_with(
            "live:worker:worker-1:heartbeat"
        )

    def test_unknown_state_with_a_dead_owner_heartbeat_needs_setup(self):
        proxy_server = self._proxy(
            metadata={"state": "unknown-state", "owner": "worker-1"},
            heartbeat_exists=False,
        )
        result = _channel_setup_needed(proxy_server, "chan")
        self.assertEqual(result, (True, "unknown-state", False))

    def test_unknown_state_with_no_owner_falls_through_to_the_existence_check(self):
        proxy_server = self._proxy(
            metadata={"state": "unknown-state"}, channel_exists=True,
        )
        # `state` was already read from the seeded metadata and stays set --
        # it is only None when metadata itself was never populated (the
        # no-metadata tests below).
        self.assertEqual(
            _channel_setup_needed(proxy_server, "chan"),
            (False, "unknown-state", False),
        )

    def test_no_metadata_but_the_channel_exists_needs_no_setup(self):
        proxy_server = self._proxy(metadata={}, channel_exists=True)
        self.assertEqual(
            _channel_setup_needed(proxy_server, "chan"), (False, None, False)
        )

    def test_no_metadata_and_no_channel_needs_setup(self):
        proxy_server = self._proxy(metadata={}, channel_exists=False)
        self.assertEqual(
            _channel_setup_needed(proxy_server, "chan"), (True, None, False)
        )

    def test_no_redis_client_skips_straight_to_the_existence_check(self):
        proxy_server = self._proxy(redis_client=False, channel_exists=True)
        self.assertEqual(
            _channel_setup_needed(proxy_server, "chan"), (False, None, False)
        )


class InitWaitAbortReasonTests(SimpleTestCase):
    def _generator_stub(self):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        return StreamGenerator(
            "chan-uuid", "client-1", "127.0.0.1", "agent", channel_name="Test",
        )

    def _proxy(self, **overrides):
        proxy_server = MagicMock()
        proxy_server.client_managers = {}
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = True  # client key present
        proxy_server.redis_client.get.return_value = None  # no last_data
        proxy_server.stream_buffers = {}
        for key, value in overrides.items():
            setattr(proxy_server, key, value)
        return proxy_server

    def test_teardown_active_returns_stopping(self):
        gen = self._generator_stub()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.is_channel_teardown_active",
            return_value=True,
        ):
            reason = gen._init_wait_abort_reason(self._proxy(), time.time())
        self.assertEqual(reason, "stopping")

    def test_client_gone_via_local_client_manager(self):
        gen = self._generator_stub()
        client_mgr = MagicMock()
        client_mgr.clients = set()  # client-1 not in it
        proxy_server = self._proxy(client_managers={"chan-uuid": client_mgr})
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.is_channel_teardown_active",
            return_value=False,
        ):
            reason = gen._init_wait_abort_reason(proxy_server, time.time())
        self.assertEqual(reason, "client_gone")

    def test_client_gone_via_redis_when_no_local_manager(self):
        gen = self._generator_stub()
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.return_value = False  # client key absent
        proxy_server.redis_client.scard.return_value = 0
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.is_channel_teardown_active",
            return_value=False,
        ):
            reason = gen._init_wait_abort_reason(proxy_server, time.time())
        self.assertEqual(reason, "client_gone")

    def test_stalled_requires_all_three_conditions(self):
        gen = self._generator_stub()

        def make_proxy(*, buffer_index=0, last_data=None, state="connecting"):
            proxy_server = self._proxy()
            proxy_server.redis_client.hget.return_value = state
            proxy_server.redis_client.get.return_value = last_data
            buf = MagicMock()
            buf.index = buffer_index
            proxy_server.stream_buffers = {"chan-uuid": buf}
            return proxy_server

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.is_channel_teardown_active",
            return_value=False,
        ), patch(
            "apps.proxy.live_proxy.output.ts.generator.ConfigHelper.channel_init_grace_period",
            return_value=0,
        ):
            # All three hold: buffer_index == 0, no last_data, connecting state.
            reason = gen._init_wait_abort_reason(
                make_proxy(buffer_index=0, last_data=None), time.time() - 1
            )
            self.assertEqual(reason, "stalled")

            # Buffer has data -- suppresses "stalled" on its own.
            reason = gen._init_wait_abort_reason(
                make_proxy(buffer_index=5, last_data=None), time.time() - 1
            )
            self.assertIsNone(reason)

            # last_data key present -- suppresses "stalled" on its own.
            reason = gen._init_wait_abort_reason(
                make_proxy(buffer_index=0, last_data="1"), time.time() - 1
            )
            self.assertIsNone(reason)


class WaitForInitializationTests(SimpleTestCase):
    def _generator_stub(self):
        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator

        return StreamGenerator(
            "chan-uuid", "client-1", "127.0.0.1", "agent", channel_name="Test",
        )

    def _drain(self, generator):
        """Run a generator to completion and return (yielded, return_value)."""
        packets = []
        try:
            while True:
                packets.append(next(generator))
        except StopIteration as stop:
            return packets, stop.value

    def test_stopping_abort(self):
        gen = self._generator_stub()
        with patch.object(gen, "_init_wait_abort_reason", return_value="stopping"), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = MagicMock()
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        self.assertEqual(len(packets), 1)
        self.assertIn(b"Error: Channel is stopping", packets[0])

    def test_client_gone_abort(self):
        gen = self._generator_stub()
        with patch.object(gen, "_init_wait_abort_reason", return_value="client_gone"), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = MagicMock()
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        self.assertIn(b"Error: Client disconnected", packets[0])

    def test_stalled_abort(self):
        gen = self._generator_stub()
        with patch.object(gen, "_init_wait_abort_reason", return_value="stalled"), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = MagicMock()
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        self.assertIn(b"Error: Connection stalled", packets[0])

    def test_ready_state_returns_true_and_yields_nothing(self):
        gen = self._generator_stub()
        proxy_server = MagicMock()
        proxy_server.redis_client.hgetall.return_value = {"state": "active"}
        with patch.object(gen, "_init_wait_abort_reason", return_value=None), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = proxy_server
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertTrue(result)
        # A spurious error packet on the ready path is exactly the bug a
        # bare `assertTrue(result)` would miss.
        self.assertEqual(packets, [])

    def test_error_state_with_a_distinctive_message(self):
        gen = self._generator_stub()
        proxy_server = MagicMock()
        proxy_server.redis_client.hgetall.return_value = {
            "state": "error", "error_message": "upstream said no",
        }
        with patch.object(gen, "_init_wait_abort_reason", return_value=None), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = proxy_server
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        # A distinctive message, not the 'Unknown error' default -- pins
        # the FIELD, not the fallback.
        self.assertIn(b"Error: upstream said no", packets[0])

    def test_the_stop_flag_path(self):
        gen = self._generator_stub()
        proxy_server = MagicMock()
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.exists.return_value = True  # stopping flag set
        with patch.object(gen, "_init_wait_abort_reason", return_value=None), \
             patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as proxy_cls:
            proxy_cls.get_instance.return_value = proxy_server
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        self.assertIn(b"Error: Channel is stopping", packets[0])

    def test_timeout_exit(self):
        gen = self._generator_stub()
        proxy_server = MagicMock()
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.exists.return_value = False
        with patch.object(gen, "_init_wait_abort_reason", return_value=None), \
             patch(
                 "apps.proxy.live_proxy.output.ts.generator.ConfigHelper.client_wait_timeout",
                 return_value=0,
             ), patch(
                 "apps.proxy.live_proxy.output.ts.generator.ProxyServer"
             ) as proxy_cls:
            proxy_cls.get_instance.return_value = proxy_server
            packets, result = self._drain(gen._wait_for_initialization())
        self.assertFalse(result)
        self.assertIn(b"Error: Initialization timeout", packets[0])
