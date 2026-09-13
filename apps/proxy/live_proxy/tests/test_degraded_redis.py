"""The degraded-Redis idioms, everywhere they repeat (Phase 2 PR 2b-4, kinds 5+6).

Two idioms, repeated across client_manager.py, channel_status.py, server.py
and channel_service.py:

  kind 5  `if not self.redis_client: return <X>` guards, where <X> differs
          per method -- None, [], 0, or the LOCAL client count. A test that
          only checks falsiness would pass against any of these; asserting
          the SPECIFIC value is what pins the method, not just the idiom.
  kind 6  `_execute_redis_command`-shaped wrappers with 2-3 except arms at
          different log levels, each returning the same degraded value for
          a different reason. Message-fragment + level assertions are what
          separate the arms; "did not raise" pins nothing.

channel_status.py's copy (:415-430) was left uncovered by Task 6
deliberately -- it lives here so it is not double-counted.
"""
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from redis.exceptions import ConnectionError, TimeoutError

from apps.proxy.live_proxy.client_manager import ClientManager


class ClientManagerFixture(SimpleTestCase):
    def _client_manager(self, *, redis_client=None):
        """A real ClientManager, with ProxyServer.get_instance() patched out.

        __init__ calls ProxyServer.get_instance() itself; patched here
        because it is the SOURCE the manager was built from, not the
        subject -- every guard/wrapper under test runs unpatched on
        self.redis_client, set directly below.
        """
        # ClientManager.__init__ imports ProxyServer function-locally
        # (`from .server import ProxyServer`), so there is no module-level
        # attribute on client_manager to patch -- the real home,
        # server.ProxyServer.get_instance, is what every import resolves to.
        with patch(
            "apps.proxy.live_proxy.server.ProxyServer.get_instance",
            return_value=MagicMock(),
        ):
            cm = ClientManager(channel_id="chan", redis_client=redis_client, worker_id="w1")
        cm._heartbeat_running = False  # stop the background thread immediately
        return cm


class ClientManagerNoRedisDegradesPerMethodTests(ClientManagerFixture):
    def test_a_client_manager_with_no_redis_degrades_per_method(self):
        """Every `if not self.redis_client` guard in ClientManager.

        Each method's degraded return is asserted individually. A loop that
        only checked `is not None` would pass with every guard returning
        the same thing, which is precisely what these guards do NOT do:
        get_total_client_count falls back to the LOCAL count, not to zero.
        """
        cm = self._client_manager(redis_client=None)
        cm.clients = {"c1", "c2"}

        self.assertIsNone(cm._execute_redis_command(lambda: "never runs"))
        self.assertEqual(cm.get_total_client_count(), 2)  # local fallback, not 0
        self.assertIsNone(cm.refresh_client_ttl())
        self.assertIsNone(cm._notify_owner_of_activity())
        # remove_client's own local_count is computed AFTER removing c1 from
        # the set (inside the lock, before the guard is reached) -- 1, not 2.
        self.assertEqual(cm.remove_client("c1"), 1)


class ExecuteRedisCommandTwoArmTests(ClientManagerFixture):
    """The Global Constraints worked example, verbatim: this module's copy."""

    def test_a_redis_connection_error_degrades_to_none_and_warns(self):
        cm = self._client_manager(redis_client=MagicMock())

        def boom():
            raise ConnectionError("redis gone")

        with self.assertLogs("live_proxy.client_manager", level="WARNING") as logs:
            result = cm._execute_redis_command(boom)

        self.assertIsNone(result)
        self.assertEqual([r.levelname for r in logs.records], ["WARNING"])
        self.assertIn("Redis connection error in ClientManager", logs.output[0])

    def test_any_other_redis_error_degrades_to_none_and_logs_at_error(self):
        cm = self._client_manager(redis_client=MagicMock())

        def boom():
            raise RuntimeError("something else")

        with self.assertLogs("live_proxy.client_manager", level="ERROR") as logs:
            result = cm._execute_redis_command(boom)

        self.assertIsNone(result)
        self.assertEqual([r.levelname for r in logs.records], ["ERROR"])
        self.assertIn("Redis command error in ClientManager", logs.output[0])


class RemoveClientAndTotalCountGuardTests(ClientManagerFixture):
    def test_remove_client_with_no_redis_returns_the_local_count_computed_before_the_guard(self):
        cm = self._client_manager(redis_client=None)
        cm.clients = {"c1", "c2", "c3"}
        # local_count is len(self.clients) AFTER c1 is removed from the set,
        # inside the `with self.lock` block, before the guard is even
        # reached -- 2, not 3 and not 0.
        self.assertEqual(cm.remove_client("c1"), 2)

    def test_get_total_client_count_falls_back_to_local_on_a_redis_exception(self):
        cm = self._client_manager(redis_client=MagicMock())
        cm.clients = {"c1", "c2"}
        cm.redis_client.scard.side_effect = RuntimeError("boom")
        with self.assertLogs("live_proxy.client_manager", level="ERROR") as logs:
            count = cm.get_total_client_count()
        self.assertEqual(count, 2)
        self.assertIn("Error getting total client count", logs.output[0])


class DoStatsUpdateGuardTests(ClientManagerFixture):
    def test_no_redis_client_skips_the_stats_update_entirely(self):
        cm = self._client_manager(redis_client=MagicMock())
        with patch(
            "core.utils.RedisClient.get_client", return_value=None
        ), patch(
            "apps.proxy.live_proxy.channel_status.build_live_channel_stats_data"
        ) as build_stats:
            cm._do_stats_update()
        build_stats.assert_not_called()


class ChannelStatusExecuteRedisCommandTests(SimpleTestCase):
    """channel_status.py's copy of the two-arm wrapper, left for this task
    by Task 6 (this file's own docstring notes why)."""

    def _run(self, command_func, *, redis_client=MagicMock()):
        from apps.proxy.live_proxy.channel_status import ChannelStatus

        with patch("apps.proxy.live_proxy.channel_status.ProxyServer") as proxy_cls:
            proxy_server = MagicMock()
            proxy_server.redis_client = redis_client
            proxy_cls.get_instance.return_value = proxy_server
            return ChannelStatus._execute_redis_command(command_func)

    def test_no_redis_client_returns_none(self):
        self.assertIsNone(self._run(lambda: "never runs", redis_client=None))

    def test_a_connection_error_degrades_to_none_and_warns(self):
        def boom():
            raise ConnectionError("gone")

        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            result = self._run(boom)
        self.assertIsNone(result)
        self.assertEqual([r.levelname for r in logs.records], ["WARNING"])
        self.assertIn("Redis connection error in ChannelStatus", logs.output[0])

    def test_any_other_error_degrades_to_none_and_logs_at_error(self):
        def boom():
            raise RuntimeError("boom")

        with self.assertLogs("live_proxy.channel_status", level="ERROR") as logs:
            result = self._run(boom)
        self.assertIsNone(result)
        self.assertEqual([r.levelname for r in logs.records], ["ERROR"])
        self.assertIn("Redis command error in ChannelStatus", logs.output[0])


class ServerExecuteRedisCommandTests(SimpleTestCase):
    """server.py's copy: three distinguishable arms, not two -- the
    ConnectionError/TimeoutError arm attempts one reconnect-and-retry
    before giving up, which the plain Exception arm does not."""

    def _server(self, *, redis_client):
        from apps.proxy.live_proxy.server import ProxyServer

        with patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=MagicMock(),
        ):
            server = ProxyServer()
        server.redis_client = redis_client
        return server

    def test_no_redis_client_returns_none(self):
        server = self._server(redis_client=None)
        self.assertIsNone(server._execute_redis_command(lambda: "never runs"))

    def test_connection_error_reconnect_fails_returns_none_and_warns(self):
        server = self._server(redis_client=MagicMock())

        def boom():
            raise ConnectionError("gone")

        # Simulate a failed reconnect: _setup_redis_connection leaves
        # redis_client None, so the "retry once" branch is skipped.
        def failed_reconnect():
            server.redis_client = None

        with patch.object(
            server, "_setup_redis_connection", side_effect=failed_reconnect
        ), self.assertLogs("live_proxy.server", level="WARNING") as logs:
            result = server._execute_redis_command(boom)

        self.assertIsNone(result)
        self.assertTrue(
            any("Redis connection lost" in line for line in logs.output)
        )

    def test_connection_error_reconnect_succeeds_retries_once(self):
        server = self._server(redis_client=MagicMock())
        reconnected_client = MagicMock()

        def successful_reconnect():
            server.redis_client = reconnected_client

        command = MagicMock(side_effect=[ConnectionError("gone"), "recovered"])

        with patch.object(
            server, "_setup_redis_connection", side_effect=successful_reconnect
        ), self.assertLogs("live_proxy.server", level="WARNING"):
            result = server._execute_redis_command(command)

        self.assertEqual(result, "recovered")
        self.assertEqual(command.call_count, 2)

    def test_reconnect_itself_raising_is_caught_and_returns_none(self):
        server = self._server(redis_client=MagicMock())

        def boom():
            raise ConnectionError("gone")

        with patch.object(
            server, "_setup_redis_connection",
            side_effect=RuntimeError("reconnect blew up"),
        ), self.assertLogs("live_proxy.server", level="ERROR") as logs:
            result = server._execute_redis_command(boom)

        self.assertIsNone(result)
        self.assertTrue(
            any("Failed to reconnect to Redis" in line for line in logs.output)
        )

    def test_any_other_error_degrades_to_none_without_attempting_reconnect(self):
        server = self._server(redis_client=MagicMock())

        def boom():
            raise RuntimeError("something else")

        with patch.object(server, "_setup_redis_connection") as reconnect, \
             self.assertLogs("live_proxy.server", level="ERROR") as logs:
            result = server._execute_redis_command(boom)

        self.assertIsNone(result)
        self.assertIn("Redis command error", logs.output[0])
        # The reconnect-and-retry machinery is specific to the connection
        # arm above -- asserting it was never touched is what separates
        # this arm from that one.
        reconnect.assert_not_called()


class PromoteChannelWhenBufferReadyGuardTests(SimpleTestCase):
    def test_no_redis_client_returns_none(self):
        from apps.proxy.live_proxy.services.channel_service import ChannelService

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as proxy_cls:
            proxy_server = MagicMock()
            proxy_server.redis_client = None
            proxy_cls.get_instance.return_value = proxy_server
            result = ChannelService.promote_channel_when_buffer_ready("chan-uuid")
        self.assertIsNone(result)
