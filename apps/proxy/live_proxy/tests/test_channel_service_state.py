"""channel_service.py's state machine and rollback arms (Phase 2 PR 2b-4, Task 9).

The axis to walk systematically, per CLAUDE.md: owner versus non-owner --
the owner switches directly, the non-owner publishes on live:events: and
polls RedisKeys.switch_status. MagicMock-Redis fixture for branch work
(fast, and the branches themselves are pure); RelayHarnessTestCase only
where a branch depends on a real Redis semantic a MagicMock cannot fake --
none of the branches here do.
"""
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelState
from apps.proxy.live_proxy.services.channel_service import ChannelService


class ChannelServiceFixture(SimpleTestCase):
    def _proxy(self, *, am_i_owner=False, **overrides):
        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.keys.return_value = []
        # Default to an immediately-confirmed switch so a test that does not
        # care about the polling outcome cannot silently burn the real 15s
        # STREAM_SWITCH_CONFIRM_TIMEOUT -- am_i_owner=False tests that DO
        # care override this explicitly (side_effect beats return_value).
        proxy_server.redis_client.get.return_value = "switched"
        proxy_server.stream_managers = {}
        proxy_server.stream_buffers = {}
        proxy_server.check_if_channel_exists.return_value = True
        # am_i_owner is a METHOD on the real ProxyServer, called as
        # proxy_server.am_i_owner(channel_id) -- setting the attribute
        # directly (as a bare bool) breaks the call at that site, so this
        # sets its return_value instead of taking the generic overrides path.
        proxy_server.am_i_owner.return_value = am_i_owner
        proxy_server.worker_id = "w1"
        for key, value in overrides.items():
            setattr(proxy_server, key, value)
        return proxy_server

    def _patched(self, proxy_server):
        return patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer.get_instance",
            return_value=proxy_server,
        )


class ChangeStreamUrlTargetStreamResolutionTests(ChannelServiceFixture):
    """The dead-in-practice (ruling 11) target_stream_id-without-url branch --
    left in place rather than removed, and still directly testable."""

    def test_a_resolve_source_error_is_returned_as_is(self):
        proxy_server = self._proxy()
        with self._patched(proxy_server), patch(
            "apps.proxy.next_source.resolve_source",
            return_value={"source": None, "error": "no capacity"},
        ):
            result = ChannelService.change_stream_url(
                "chan-uuid", target_stream_id=42,
            )
        self.assertEqual(result, {"status": "error", "message": "no capacity"})

    def test_a_resolve_source_success_extracts_every_field(self):
        proxy_server = self._proxy(am_i_owner=True)
        manager = MagicMock()
        manager.url = "http://old.example/a.ts"
        manager.update_url.return_value = True
        proxy_server.stream_managers = {"chan-uuid": manager}
        with self._patched(proxy_server), patch(
            "apps.proxy.next_source.resolve_source",
            return_value={
                "source": {
                    "url": "http://new.example/b.ts", "user_agent": "ua",
                    "stream_name": "Stream B", "channel_name": "Chan",
                    "m3u_profile_name": "Profile A", "m3u_profile_id": 7,
                },
                "error": None,
            },
        ):
            result = ChannelService.change_stream_url(
                "chan-uuid", target_stream_id=42,
            )
        manager.update_url.assert_called_once_with(
            "http://new.example/b.ts", 42, 7,
        )
        self.assertEqual(result["status"], "success")


class ChangeStreamUrlDiagnosticsAndRecoveryTests(ChannelServiceFixture):
    def test_a_redis_keys_lookup_failure_is_logged_and_diagnostics_continue(self):
        proxy_server = self._proxy(am_i_owner=True)
        proxy_server.redis_client.keys.side_effect = RuntimeError("boom")
        with self._patched(proxy_server), self.assertLogs(
            "live_proxy", level="ERROR"
        ) as logs:
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        self.assertIn("Error checking Redis keys", logs.output[0])
        # The lookup failing does not abort the call -- it still answers.
        self.assertIn(result["status"], ("success", "recovered"))

    def test_a_missing_channel_with_leftover_redis_keys_is_recovered(self):
        proxy_server = self._proxy(check_if_channel_exists=lambda *_: False)
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.redis_client.keys.return_value = [b"live:channel:chan-uuid:metadata"]
        with self._patched(proxy_server):
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        proxy_server.initialize_channel.assert_called_once_with(
            "http://new.example/a.ts", "chan-uuid", None,
        )
        self.assertEqual(result["status"], "recovered")

    def test_a_missing_channel_with_no_redis_keys_is_an_error_with_diagnostics(self):
        proxy_server = self._proxy()
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.redis_client.keys.return_value = []
        with self._patched(proxy_server):
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Channel not found")
        self.assertIn("diagnostics", result)


class ChangeStreamUrlOwnerMetadataTests(ChannelServiceFixture):
    def test_a_failed_update_writes_the_managers_actual_url_not_the_requested_one(self):
        proxy_server = self._proxy(am_i_owner=True)
        manager = MagicMock()
        manager.url = "http://actual.example/still-playing.ts"
        manager.update_url.return_value = False
        proxy_server.stream_managers = {"chan-uuid": manager}
        with self._patched(proxy_server), patch.object(
            ChannelService, "_update_channel_metadata"
        ) as update_metadata:
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://requested.example/new.ts",
                user_agent="ua",
            )
        update_metadata.assert_called_once_with(
            "chan-uuid", "http://actual.example/still-playing.ts", "ua",
        )
        self.assertFalse(result["success"])

    def test_a_metadata_write_exception_is_logged_and_marks_metadata_not_updated(self):
        proxy_server = self._proxy(am_i_owner=True)
        manager = MagicMock()
        manager.url = "http://old.example/a.ts"
        manager.update_url.return_value = True
        proxy_server.stream_managers = {"chan-uuid": manager}
        with self._patched(proxy_server), patch.object(
            ChannelService, "_update_channel_metadata",
            side_effect=RuntimeError("redis down"),
        ), self.assertLogs("live_proxy", level="ERROR") as logs:
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/b.ts",
            )
        self.assertFalse(result["metadata_updated"])
        self.assertIn("Error updating Redis metadata", logs.output[0])


class ChangeStreamUrlNonOwnerPublishTests(ChannelServiceFixture):
    def test_clearing_stale_switch_status_failure_does_not_abort_the_publish(self):
        proxy_server = self._proxy(am_i_owner=False)
        proxy_server.redis_client.delete.side_effect = RuntimeError("boom")
        proxy_server.redis_client.get.return_value = "switched"
        with self._patched(proxy_server), patch.object(
            ChannelService, "_publish_stream_switch_event"
        ) as publish, self.assertLogs("live_proxy", level="WARNING") as logs:
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        self.assertIn("Could not clear switch status", logs.output[0])
        publish.assert_called_once()
        self.assertTrue(result["success"])

    def test_a_polling_failure_degrades_to_not_confirmed(self):
        proxy_server = self._proxy(am_i_owner=False)
        proxy_server.redis_client.get.side_effect = RuntimeError("connection reset")
        with self._patched(proxy_server), patch.object(
            ChannelService, "_publish_stream_switch_event"
        ), self.assertLogs("live_proxy", level="WARNING") as logs:
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        self.assertIn("Error polling switch status", logs.output[0])
        self.assertFalse(result["success"])
        self.assertFalse(result.get("confirmed", True))

    def test_no_redis_client_cannot_publish_at_all(self):
        proxy_server = self._proxy(am_i_owner=False, redis_client=None)
        with self._patched(proxy_server):
            result = ChannelService.change_stream_url(
                "chan-uuid", new_url="http://new.example/a.ts",
            )
        self.assertFalse(result["success"])
        self.assertFalse(result["event_published"])
        self.assertEqual(result["error"], "Redis not available for pubsub")


class ChannelProxyIsActiveTests(SimpleTestCase):
    """The 6-statement static: no ProxyServer involved, redis_client is a
    plain argument."""

    def test_no_metadata_is_not_active(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = False
        self.assertFalse(
            ChannelService._channel_proxy_is_active(redis_client, "chan-uuid")
        )

    def test_metadata_with_no_state_field_is_not_active(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = True
        redis_client.hget.return_value = None
        self.assertFalse(
            ChannelService._channel_proxy_is_active(redis_client, "chan-uuid")
        )

    def test_a_bytes_state_is_decoded_before_comparison(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = True
        redis_client.hget.return_value = b"active"
        self.assertTrue(
            ChannelService._channel_proxy_is_active(redis_client, "chan-uuid")
        )

    def test_a_terminal_state_is_not_active(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = True
        redis_client.hget.return_value = "stopped"
        self.assertFalse(
            ChannelService._channel_proxy_is_active(redis_client, "chan-uuid")
        )


class CancelPendingShutdownTests(ChannelServiceFixture):
    def test_no_redis_client_returns_false(self):
        proxy_server = self._proxy(redis_client=None)
        with self._patched(proxy_server):
            self.assertFalse(ChannelService.cancel_pending_shutdown("chan-uuid"))

    def test_a_stop_in_progress_refuses_to_cancel(self):
        proxy_server = self._proxy(_stopping_channels={"chan-uuid"})
        with self._patched(proxy_server):
            self.assertFalse(ChannelService.cancel_pending_shutdown("chan-uuid"))

    def test_nothing_pending_returns_false(self):
        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = False
        with self._patched(proxy_server), patch.object(
            ChannelService, "is_shutdown_pending", return_value=False,
        ):
            self.assertFalse(ChannelService.cancel_pending_shutdown("chan-uuid"))

    def test_a_pending_shutdown_reverts_a_stopping_state_to_active(self):
        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = True  # had_pending
        proxy_server.redis_client.hget.return_value = ChannelState.STOPPING
        with self._patched(proxy_server), patch.object(
            ChannelService, "_channel_proxy_is_active", return_value=False,
        ):
            self.assertTrue(ChannelService.cancel_pending_shutdown("chan-uuid"))
        hset_calls = proxy_server.redis_client.hset.call_args_list
        self.assertTrue(
            any(
                call.kwargs["mapping"].get("state") == ChannelState.ACTIVE
                for call in hset_calls
            )
        )

    def test_a_leaked_stopping_flag_is_deleted(self):
        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hget.return_value = None
        with self._patched(proxy_server), patch.object(
            ChannelService, "_channel_proxy_is_active", return_value=False,
        ):
            self.assertTrue(ChannelService.cancel_pending_shutdown("chan-uuid"))
        proxy_server.redis_client.delete.assert_called()

    def test_reservation_failure_is_logged_and_not_fatal(self):
        from apps.proxy import control_plane

        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hget.return_value = None
        with self._patched(proxy_server), patch.object(
            ChannelService, "_channel_proxy_is_active", return_value=True,
        ), patch.object(
            control_plane, "next_source",
            side_effect=control_plane.ControlPlaneRefused(403, "/next-source"),
        ), self.assertLogs("live_proxy", level="WARNING") as logs:
            result = ChannelService.cancel_pending_shutdown("chan-uuid")
        self.assertTrue(result)
        self.assertIn("Could not re-reserve stream", logs.output[0])

    def test_a_next_source_answer_with_no_source_is_logged(self):
        from apps.proxy import control_plane

        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hget.return_value = None
        with self._patched(proxy_server), patch.object(
            ChannelService, "_channel_proxy_is_active", return_value=True,
        ), patch.object(
            control_plane, "next_source",
            return_value={"source": None, "error": "no candidates"},
        ), self.assertLogs("live_proxy", level="WARNING") as logs:
            result = ChannelService.cancel_pending_shutdown("chan-uuid")
        self.assertTrue(result)
        self.assertIn("Could not re-reserve stream", logs.output[0])

    def test_a_successful_re_reservation_writes_the_new_slot(self):
        from apps.proxy import control_plane

        proxy_server = self._proxy(_stopping_channels=set())
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hget.return_value = None
        with self._patched(proxy_server), patch.object(
            ChannelService, "_channel_proxy_is_active", return_value=True,
        ), patch.object(
            control_plane, "next_source",
            return_value={
                "source": {"slot_reserved": True, "stream_id": 42, "m3u_profile_id": 7},
                "error": None,
            },
        ):
            result = ChannelService.cancel_pending_shutdown("chan-uuid")
        self.assertTrue(result)
        hset_calls = proxy_server.redis_client.hset.call_args_list
        self.assertTrue(
            any(
                call.kwargs["mapping"].get("stream_id") == "42"
                for call in hset_calls
            )
        )


class ValidateChannelStateTests(ChannelServiceFixture):
    def test_no_redis_client(self):
        proxy_server = self._proxy(redis_client=None)
        with self._patched(proxy_server):
            result = ChannelService.validate_channel_state("chan-uuid")
        self.assertEqual(result, (False, None, None, {"error": "Redis not available"}))

    def test_no_metadata(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.return_value = False
        with self._patched(proxy_server):
            result = ChannelService.validate_channel_state("chan-uuid")
        self.assertEqual(result, (False, None, None, {"error": "No channel metadata"}))

    def test_an_invalid_state_is_rejected(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.return_value = True
        proxy_server.redis_client.hgetall.return_value = {
            "state": "stopped", "owner": "w1",
        }
        with self._patched(proxy_server):
            valid, state, owner, details = ChannelService.validate_channel_state(
                "chan-uuid"
            )
        self.assertFalse(valid)
        self.assertEqual(state, "stopped")
        self.assertEqual(details["error"], "Invalid state: stopped")

    def test_a_valid_state_with_a_dead_owner_is_rejected(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.side_effect = [True, False]
        proxy_server.redis_client.hgetall.return_value = {
            "state": ChannelState.ACTIVE, "owner": "w1",
        }
        with self._patched(proxy_server):
            valid, state, owner, details = ChannelService.validate_channel_state(
                "chan-uuid"
            )
        self.assertFalse(valid)
        self.assertEqual(details["error"], "Owner not active")

    def test_a_valid_state_with_no_recent_data_field_is_accepted(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.side_effect = [True, True]
        proxy_server.redis_client.hgetall.return_value = {
            "state": ChannelState.ACTIVE, "owner": "w1",
        }
        proxy_server.redis_client.get.return_value = None
        with self._patched(proxy_server):
            valid, state, owner, details = ChannelService.validate_channel_state(
                "chan-uuid"
            )
        self.assertTrue(valid)
        self.assertNotIn("last_data_age", details)

    def test_stale_data_beyond_the_30s_threshold_is_rejected(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.side_effect = [True, True]
        proxy_server.redis_client.hgetall.return_value = {
            "state": ChannelState.ACTIVE, "owner": "w1",
        }
        with self._patched(proxy_server), patch(
            "apps.proxy.live_proxy.services.channel_service.time.time",
            return_value=1031.0,
        ):
            proxy_server.redis_client.get.return_value = "1000.0"
            valid, state, owner, details = ChannelService.validate_channel_state(
                "chan-uuid"
            )
        self.assertFalse(valid)
        self.assertIn("No data for 31.0s", details["error"])

    def test_fresh_data_within_the_threshold_is_accepted(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.side_effect = [True, True]
        proxy_server.redis_client.hgetall.return_value = {
            "state": ChannelState.ACTIVE, "owner": "w1",
        }
        with self._patched(proxy_server), patch(
            "apps.proxy.live_proxy.services.channel_service.time.time",
            return_value=1010.0,
        ):
            proxy_server.redis_client.get.return_value = "1000.0"
            valid, state, owner, details = ChannelService.validate_channel_state(
                "chan-uuid"
            )
        self.assertTrue(valid)
        self.assertEqual(details["last_data_age"], 10.0)

    def test_an_unexpected_exception_is_caught_and_reported(self):
        proxy_server = self._proxy()
        proxy_server.redis_client.exists.side_effect = RuntimeError("boom")
        with self._patched(proxy_server), self.assertLogs(
            "live_proxy", level="ERROR"
        ) as logs:
            result = ChannelService.validate_channel_state("chan-uuid")
        self.assertEqual(result[0], False)
        self.assertEqual(result[3]["error"], "Exception: boom")
        self.assertIn("Error validating channel state", logs.output[0])


class StopChannelsTests(SimpleTestCase):
    def test_an_empty_list_calls_nothing(self):
        with patch.object(ChannelService, "stop_channel") as stop_channel:
            ChannelService.stop_channels([])
        stop_channel.assert_not_called()

    def test_falsy_identifiers_are_skipped(self):
        with patch.object(ChannelService, "stop_channel") as stop_channel:
            ChannelService.stop_channels([None, "", "chan-1"])
        stop_channel.assert_called_once_with("chan-1")

    def test_a_per_channel_failure_does_not_abort_the_rest(self):
        with patch.object(
            ChannelService, "stop_channel",
            side_effect=[RuntimeError("boom"), None],
        ) as stop_channel, self.assertLogs("live_proxy", level="WARNING") as logs:
            ChannelService.stop_channels(["chan-1", "chan-2"])
        self.assertEqual(stop_channel.call_count, 2)
        self.assertIn("Failed to stop proxy session", logs.output[0])


class ClientManagerFixture(SimpleTestCase):
    """Task 9 Step 3: client_manager's rollback, TTL and sweep arms.

    Own copy of the ProxyServer.get_instance patch, per this programme's
    convention that each test module keeps its own fixture rather than
    sharing one -- test_degraded_redis.py has an equivalent for kind 5/6
    coverage of the same class; this one drives add_client/refresh_client_ttl
    end to end instead.
    """

    def _client_manager(self, *, redis_client=None):
        from apps.proxy.live_proxy.client_manager import ClientManager

        with patch(
            "apps.proxy.live_proxy.server.ProxyServer.get_instance",
            return_value=MagicMock(),
        ):
            cm = ClientManager(channel_id="chan", redis_client=redis_client, worker_id="w1")
        cm._heartbeat_running = False
        return cm


class AddClientRollbackTests(ClientManagerFixture):
    def test_no_user_agent_logs_and_still_succeeds(self):
        cm = self._client_manager(redis_client=MagicMock())
        with patch.object(ChannelService, "cancel_pending_shutdown", return_value=False), \
             patch.object(ChannelService, "promote_channel_when_buffer_ready"):
            result = cm.add_client("c1", "127.0.0.1")
        self.assertEqual(result, 1)

    def test_a_failure_mid_registration_rolls_back_the_local_client(self):
        cm = self._client_manager(redis_client=MagicMock())
        cm.redis_client.publish.side_effect = RuntimeError("boom")
        with patch.object(
            ChannelService, "cancel_pending_shutdown", return_value=False,
        ), self.assertLogs("live_proxy.client_manager", level="ERROR") as logs:
            result = cm.add_client("c1", "127.0.0.1", user_agent="ua")
        self.assertFalse(result)
        self.assertNotIn("c1", cm.clients)
        self.assertNotIn("c1", cm._registered_clients)
        self.assertIn("Error adding client c1", logs.output[0])


class RefreshClientTtlTests(ClientManagerFixture):
    def test_refreshes_every_local_client_key_and_the_set_with_a_non_default_ttl(self):
        cm = self._client_manager(redis_client=MagicMock())
        cm.clients = {"c1", "c2"}
        # A non-default TTL is the pin: a test that left client_ttl at
        # whatever ConfigHelper's own default is would pass even with the
        # computation deleted and a hard-coded default substituted.
        cm.client_ttl = 12345
        cm.refresh_client_ttl()
        cm.redis_client.expire.assert_any_call("live:channel:chan:clients:c1", 12345)
        cm.redis_client.expire.assert_any_call("live:channel:chan:clients:c2", 12345)
        cm.redis_client.expire.assert_any_call(cm.client_set_key, 12345)

    def test_a_redis_failure_during_refresh_is_logged_not_raised(self):
        cm = self._client_manager(redis_client=MagicMock())
        cm.clients = {"c1"}
        cm.redis_client.expire.side_effect = RuntimeError("boom")
        with self.assertLogs("live_proxy.client_manager", level="ERROR") as logs:
            cm.refresh_client_ttl()  # must not raise
        self.assertIn("Error refreshing client TTL", logs.output[0])


class ClearAllClientsTests(SimpleTestCase):
    def test_an_empty_client_set_returns_zero_without_a_pipeline(self):
        from apps.proxy.live_proxy.client_manager import ClientManager

        redis_client = MagicMock()
        redis_client.smembers.return_value = set()
        result = ClientManager.clear_all_clients(redis_client, "chan")
        self.assertEqual(result, 0)
        redis_client.pipeline.assert_not_called()

    def test_every_client_metadata_key_is_deleted_plus_the_set_itself(self):
        from apps.proxy.live_proxy.client_manager import ClientManager

        redis_client = MagicMock()
        redis_client.smembers.return_value = {b"c1", "c2"}
        pipe = redis_client.pipeline.return_value
        result = ClientManager.clear_all_clients(redis_client, "chan")
        self.assertEqual(result, 2)
        deleted_keys = {call.args[0] for call in pipe.delete.call_args_list}
        self.assertEqual(
            deleted_keys,
            {"live:channel:chan:clients:c1", "live:channel:chan:clients:c2",
             "live:channel:chan:clients"},
        )
        pipe.execute.assert_called_once()
