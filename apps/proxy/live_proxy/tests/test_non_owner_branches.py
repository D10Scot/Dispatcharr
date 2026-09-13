"""The non-owner second branch, everywhere it repeats (Phase 2 PR 2b-4,
Task 10, kind 8).

CLAUDE.md names owner/follower as a systematic axis: three PRs in this
programme have had a defect hiding in one branch. server.py's own gates are
built with a real ProxyServer() (RedisClient.get_client patched during
construction, same pattern as test_degraded_redis.py's ServerExecuteRedisCommand
Tests) and a MagicMock redis_client attached afterward -- the gates
themselves are pure conditional logic over Redis reads, not atomicity, so
MagicMock is the right tool per this stage's own methodology note.

apps.proxy.live_proxy.server.time IS the real global time module (server.py
just does `import time`), so patching `...server.time.time` is process-wide
-- see test_stream_ts_retry_loop.py's docstring for the full account of why
a finite side_effect list is fragile against other tests' leaked background
threads/greenlets under a full-package run. Same fix here.
"""
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.client_manager import ClientManager


def _resilient_time_sequence(values):
    """A time.time() side_effect that repeats its last value once exhausted,
    rather than raising StopIteration on an unexpected extra call."""
    state = {"i": 0}

    def _next():
        i = state["i"]
        state["i"] += 1
        return values[i] if i < len(values) else values[-1]

    return _next


class ServerFixture(SimpleTestCase):
    def _server(self, *, redis_client=None, worker_id="w1"):
        from apps.proxy.live_proxy.server import ProxyServer

        with patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=MagicMock(),
        ):
            server = ProxyServer()
        server.redis_client = redis_client if redis_client is not None else MagicMock()
        server.worker_id = worker_id
        return server


class EnsureOutputFormatNonOwnerTests(ServerFixture):
    def test_gate_b_prime_active_on_another_worker_returns_true_without_polling(self):
        server = self._server()
        server.redis_client.get.side_effect = ["active", "other-worker"]
        with patch.object(server, "am_i_owner") as am_i_owner:
            result = server.ensure_output_format("chan-uuid", "fmp4")
        self.assertTrue(result)
        # The early return at gate B' fires before the ownership check at
        # gate C' is ever reached.
        am_i_owner.assert_not_called()

    def test_gate_c_prime_non_owner_polls_until_the_owner_starts_it(self):
        server = self._server()
        server.am_i_owner = MagicMock(return_value=False)
        # First .get(): state != 'active', so gate B' is skipped. Then the
        # poll loop's own .get() calls: not yet active, then active.
        server.redis_client.get.side_effect = [None, None, "active"]
        with patch(
            "apps.proxy.live_proxy.server.gevent.sleep"
        ), patch(
            "apps.proxy.live_proxy.server.time.time",
            side_effect=_resilient_time_sequence([0.0, 0.0, 0.1, 0.2]),
        ):
            result = server.ensure_output_format("chan-uuid", "fmp4")
        self.assertTrue(result)
        server.redis_client.publish.assert_called_once()

    def test_gate_c_prime_times_out_when_the_owner_never_starts_it(self):
        server = self._server()
        server.am_i_owner = MagicMock(return_value=False)
        server.redis_client.get.return_value = None  # never becomes active
        with patch(
            "apps.proxy.live_proxy.server.gevent.sleep"
        ), patch(
            "apps.proxy.live_proxy.server.time.time",
            side_effect=_resilient_time_sequence([0.0, 0.0, 5.1]),
        ), self.assertLogs("live_proxy.server", level="WARNING") as logs:
            result = server.ensure_output_format("chan-uuid", "fmp4")
        self.assertFalse(result)
        self.assertIn("did not start manager within 5s", logs.output[-1])


class EnsureOutputProfileNonOwnerTests(ServerFixture):
    """Gates B and C. OutputProfileManager is patched here -- it is a
    COLLABORATOR ensure_output_profile calls and uses the output_buffer of,
    not the subject under test (that is still ensure_output_profile's own
    branch selection); OutputProfileManager.start()'s real lock-acquisition
    needs real Redis semantics a MagicMock cannot fake reliably, which is
    exactly the RelayHarnessTestCase line this stage's methodology note
    draws -- patching the collaborator here is the Tier-A-compatible way to
    stay on the right side of it without a harness for these two gates."""

    def test_gate_b_active_elsewhere_wires_a_reader_buffer(self):
        server = self._server()
        server.redis_client.get.side_effect = ["active", "other-worker"]
        fake_manager = MagicMock()
        fake_manager.output_buffer = "the-shared-buffer"
        with patch(
            "apps.proxy.live_proxy.server.OutputProfileManager",
            return_value=fake_manager,
        ) as manager_cls, patch.object(server, "am_i_owner") as am_i_owner:
            result = server.ensure_output_profile("chan-uuid", 7, ["ffmpeg"])
        self.assertTrue(result)
        manager_cls.assert_called_once()
        fake_manager.start.assert_called_once()
        self.assertEqual(
            server.profile_buffers["chan-uuid"][7], "the-shared-buffer"
        )
        # am_i_owner is called exactly once here -- unconditionally, at the
        # top, for the function's own debug log -- and gate B's early return
        # then fires before the SECOND potential call at gate C's own
        # ownership check would happen.
        am_i_owner.assert_called_once()

    def test_gate_c_non_owner_polls_until_the_owner_starts_it(self):
        server = self._server()
        server.am_i_owner = MagicMock(return_value=False)
        # First two .get()s: the pre-poll "another worker owns it" check
        # (state, then owner) -- both come back not-active/None, so gate B
        # is skipped. Then the poll loop's own .get(): not yet, then active.
        server.redis_client.get.side_effect = [None, "active"]
        fake_manager = MagicMock()
        fake_manager.output_buffer = "the-shared-buffer"
        with patch(
            "apps.proxy.live_proxy.server.OutputProfileManager",
            return_value=fake_manager,
        ), patch(
            "apps.proxy.live_proxy.server.gevent.sleep"
        ), patch(
            "apps.proxy.live_proxy.server.time.time",
            side_effect=_resilient_time_sequence([0.0, 0.0, 0.1, 0.2]),
        ):
            result = server.ensure_output_profile("chan-uuid", 7, ["ffmpeg"])
        self.assertTrue(result)
        server.redis_client.publish.assert_called_once()
        self.assertEqual(
            server.profile_buffers["chan-uuid"][7], "the-shared-buffer"
        )

    def test_gate_c_times_out_when_the_owner_never_starts_it(self):
        server = self._server()
        server.am_i_owner = MagicMock(return_value=False)
        server.redis_client.get.return_value = None  # never becomes active
        with patch(
            "apps.proxy.live_proxy.server.gevent.sleep"
        ), patch(
            "apps.proxy.live_proxy.server.time.time",
            side_effect=_resilient_time_sequence([0.0, 0.0, 5.1]),
        ), self.assertLogs("live_proxy.server", level="WARNING") as logs:
            result = server.ensure_output_profile("chan-uuid", 7, ["ffmpeg"])
        self.assertFalse(result)
        self.assertIn("did not start transcode within 5s", logs.output[-1])


class ClientManagerNonOwnerFixture(SimpleTestCase):
    def _client_manager(self, *, proxy_server):
        with patch(
            "apps.proxy.live_proxy.server.ProxyServer.get_instance",
            return_value=proxy_server,
        ):
            cm = ClientManager(channel_id="chan", redis_client=MagicMock(), worker_id="w1")
        cm._heartbeat_running = False
        return cm


class RemoveClientNonOwnerGatesTests(ClientManagerNonOwnerFixture):
    """client_manager.py:358-396's three-way (not two-way) non-owner split.

    Two traps, both of which make the obvious fixture run the wrong branch
    (documented at length in the plan this task comes from):

    Trap 1 -- gate F (the lease-expiry promotion at :361-364) re-acquires
    ownership mid-function. Seeding a foreign owner alone is not enough:
    the fixture must control _has_local_upstream_activity, since THAT is
    what the promotion attempt is gated on, not am_i_owner directly.

    Trap 2 -- :366-396 is a three-way (if/elif/else), not if/else. Gate D
    (the elif) and gate E (the else) are reached by failing DIFFERENT
    conjuncts of the same condition, so a single lever cannot select
    between them: gate E holds _has_local_upstream_activity False
    (indifferent to extend_ownership); gate D needs it True and must
    therefore force extend_ownership False -- the lever gate E declines.
    """

    def test_gate_f_a_stale_lease_is_reclaimed_via_extend_ownership(self):
        proxy_server = MagicMock()
        proxy_server.am_i_owner.return_value = False
        proxy_server._has_local_upstream_activity.return_value = True
        proxy_server.extend_ownership.return_value = True
        proxy_server.output_managers = {}
        proxy_server.profile_managers = {}
        cm = self._client_manager(proxy_server=proxy_server)
        cm.redis_client.scard.return_value = 1  # remaining != 0
        cm.clients = {"c1"}

        with self.assertLogs("live_proxy.client_manager", level="DEBUG") as logs:
            cm.remove_client("c1")

        proxy_server.extend_ownership.assert_called_once_with("chan")
        # The promotion took the OWNER branch (its own debug log), not the
        # non-owner publish -- that is the product gate F's promotion buys.
        self.assertTrue(
            any("Owner handling CLIENT_DISCONNECTED" in line for line in logs.output)
        )
        cm.redis_client.publish.assert_not_called()

    def test_gate_d_local_upstream_survives_the_lease_without_reclaiming_it(self):
        proxy_server = MagicMock()
        proxy_server.am_i_owner.return_value = False
        proxy_server._has_local_upstream_activity.return_value = True
        proxy_server.extend_ownership.return_value = False  # reclaim fails
        cm = self._client_manager(proxy_server=proxy_server)
        cm.redis_client.scard.return_value = 0  # remaining == 0
        cm.clients = {"c1"}

        with self.assertLogs("live_proxy.client_manager", level="WARNING") as logs:
            cm.remove_client("c1")

        self.assertTrue(
            any(
                "without owner lock - stopping channel" in line
                for line in logs.output
            )
        )
        # Gate D schedules a local disconnect handler -- it does NOT
        # publish, which is what separates it from gate E.
        cm.redis_client.publish.assert_not_called()
        proxy_server._spawn_on_hub.assert_called_once_with(
            proxy_server.handle_client_disconnect, "chan"
        )

    def test_gate_e_no_local_upstream_publishes_for_the_owner_to_see(self):
        proxy_server = MagicMock()
        proxy_server.am_i_owner.return_value = False
        proxy_server._has_local_upstream_activity.return_value = False
        cm = self._client_manager(proxy_server=proxy_server)
        # remaining > 0 is deliberately over-constrained (the plan's own
        # ruling): gate E is reachable at remaining == 0 too once
        # _has_local_upstream_activity is False, but pinning remaining > 0
        # makes this test independent of that second condition entirely.
        cm.redis_client.scard.return_value = 3
        cm.redis_client.hget.return_value = None  # -> "unknown", not a MagicMock
        cm.clients = {"c1"}

        cm.remove_client("c1")

        cm.redis_client.publish.assert_called_once()
        channel, payload = cm.redis_client.publish.call_args.args
        import json as _json
        data = _json.loads(payload)
        self.assertEqual(data["event"], "client_disconnected")
        self.assertEqual(data["remaining_clients"], 3)
        proxy_server._spawn_on_hub.assert_not_called()
