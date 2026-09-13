"""Kind 10: small error arms in already-96%+ boundary modules (Phase 2 PR
2b-4, Task 11). Cheap, and these are the modules a Go port must match
exactly. Every line enumerated from a fresh live-path.json measurement,
not the plan's own table -- authorize.py alone drifted +17 statements
since the reachability brief.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import APIException

from apps.accounts.models import User
from apps.proxy import authorize, control_plane, relay_client
from apps.proxy.config import TSConfig as Config
from apps.proxy.live_proxy.config_helper import ConfigHelper


class ConfigHelperDefaultLadderTests(SimpleTestCase):
    """A pin that supplies the default pins nothing: Config.CONNECTION_TIMEOUT
    etc. are REAL class attributes equal to ConfigHelper's own fallback
    literal (the same BUFFER_CHUNK_SIZE-shaped trap CLAUDE.md documents), so
    every assertion here patches a non-default value rather than reading the
    coincidentally-matching default."""

    def test_connection_timeout_reads_through_config(self):
        with patch.object(Config, "CONNECTION_TIMEOUT", 999):
            self.assertEqual(ConfigHelper.connection_timeout(), 999)

    def test_keepalive_interval_reads_through_config(self):
        with patch.object(Config, "KEEPALIVE_INTERVAL", 12.5):
            self.assertEqual(ConfigHelper.keepalive_interval(), 12.5)

    def test_retry_wait_interval_reads_through_config(self):
        with patch.object(Config, "RETRY_WAIT_INTERVAL", 3.25):
            self.assertEqual(ConfigHelper.retry_wait_interval(), 3.25)

    def test_channel_client_wait_period_delegates_to_config(self):
        with patch.object(
            Config, "get_channel_client_wait_period", return_value=77
        ) as delegate:
            self.assertEqual(ConfigHelper.channel_client_wait_period(), 77)
        delegate.assert_called_once()


class LiveProxyAppsReadyTests(SimpleTestCase):
    def test_ready_starts_the_proxy_server_outside_manage_py(self):
        from apps.proxy.live_proxy.apps import LiveProxyConfig

        config = LiveProxyConfig.__new__(LiveProxyConfig)
        with patch("sys.argv", ["/usr/bin/uwsgi"]), patch(
            "apps.proxy.live_proxy.server.ProxyServer.get_instance"
        ) as get_instance:
            config.ready()
        get_instance.assert_called_once()

    def test_ready_is_a_no_op_under_manage_py(self):
        from apps.proxy.live_proxy.apps import LiveProxyConfig

        config = LiveProxyConfig.__new__(LiveProxyConfig)
        with patch("sys.argv", ["manage.py", "test"]), patch(
            "apps.proxy.live_proxy.server.ProxyServer.get_instance"
        ) as get_instance:
            config.ready()
        get_instance.assert_not_called()


class UserCanAccessChannelAdminBypassTests(SimpleTestCase):
    def test_an_admin_passes_regardless_of_channel_profile_membership(self):
        user = MagicMock()
        user.user_level = User.UserLevel.ADMIN
        channel = MagicMock()
        channel.user_level = User.UserLevel.ADMIN
        self.assertTrue(authorize.user_can_access_channel(user, channel))
        # The admin bypass is what makes this pass -- a membership query
        # would have needed channel.objects.filter, never reached here.
        channel.channel_profiles.count.assert_not_called()


class ResolveOutputProfileInvalidParamTests(SimpleTestCase):
    def test_an_invalid_output_profile_query_param_is_ignored(self):
        request = MagicMock()
        request.GET = {"output_profile": "not-an-int"}
        self.assertIsNone(authorize.resolve_output_profile(request, user=None))

    def test_an_invalid_custom_property_output_profile_is_ignored(self):
        request = MagicMock()
        request.GET = {}
        user = MagicMock()
        user.custom_properties = {"output_profile": "not-an-int"}
        self.assertIsNone(authorize.resolve_output_profile(request, user=user))


class ResolveOutputFormatForceOverrideTests(SimpleTestCase):
    def test_a_forced_format_short_circuits_before_the_request_is_read(self):
        request = MagicMock()
        result = authorize.resolve_output_format(request, user=None, force="fmp4")
        self.assertEqual(result, "fmp4")
        request.GET.get.assert_not_called()


class DrfUserApiExceptionArmTests(SimpleTestCase):
    def test_a_non_authentication_api_exception_degrades_to_none(self):
        # Distinct from AuthenticationFailed's own arm (which raises
        # AuthorizeDenied): a broader DRF APIException must degrade to
        # anonymous rather than propagate or deny.
        http_request = MagicMock()
        http_request.user = "original-user-sentinel"
        with patch(
            "apps.proxy.authorize.Request",
            side_effect=APIException("service unavailable"),
        ):
            result = authorize._drf_user(http_request)
        self.assertIsNone(result)


class ResolveChannelXcNonNumericIdentifierTests(SimpleTestCase):
    def test_a_non_numeric_xc_identifier_is_404_not_500(self):
        from apps.proxy.authorize import AuthorizeDenied, SURFACE_LIVE_XC

        with self.assertRaises(AuthorizeDenied) as caught:
            authorize._resolve_channel(SURFACE_LIVE_XC, "not-an-int")
        self.assertEqual(caught.exception.status, 404)


class ControlPlanePostEventsAlreadyDownDebugTests(SimpleTestCase):
    def test_a_misconfigured_host_while_already_down_logs_at_debug_not_error(self):
        control_plane._events_down = True
        self.addCleanup(setattr, control_plane, "_events_down", False)
        exc = control_plane.ImproperlyConfigured("bad host")
        exc.var_name = "DISPATCHARR_RELAY_BASE_URL"
        with patch.object(
            control_plane, "_post", side_effect=exc
        ), self.assertLogs("apps.proxy.control_plane", level="DEBUG") as logs:
            result = control_plane.post_events([{"type": "x"}])
        self.assertFalse(result)
        self.assertEqual([r.levelname for r in logs.records], ["DEBUG"])
        self.assertIn("is misconfigured", logs.output[0])
        # Stays down -- this is the "still down" branch, not the recovery one.
        self.assertTrue(control_plane._events_down)


class ControlPlaneSpawnGeventBranchTests(SimpleTestCase):
    def test_spawn_uses_gevent_when_monkey_patched_and_async_is_wanted(self):
        fn = MagicMock()
        with patch(
            "core.utils._should_use_sync_websocket_send", return_value=False,
        ), patch(
            "core.utils._is_gevent_monkey_patched", return_value=True,
        ), patch("gevent.spawn") as spawn:
            control_plane._spawn(fn, "arg1", "arg2")
        spawn.assert_called_once_with(fn, "arg1", "arg2")
        fn.assert_not_called()  # gevent.spawn is patched, so fn itself never runs


class RelayClientStopChannelsGenericExceptionArmTests(SimpleTestCase):
    def test_a_non_relay_shaped_bug_is_logged_and_the_loop_continues(self):
        # Distinct from RelayUnavailable/RelayRefused/ImproperlyConfigured:
        # a bug in stop_channel itself must not abort the batch, and must
        # not be mistaken for a relay-wide outage.
        seen = []

        def _bug_on_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                raise RuntimeError("bug in stop_channel")
            return {"status": "success"}

        with patch.object(
            relay_client, "stop_channel", side_effect=_bug_on_the_second
        ), self.assertLogs(relay_client.logger, level="WARNING") as logs:
            stopped = relay_client.stop_channels(iter(["a", "b", "c"]))
        self.assertEqual(seen, ["a", "b", "c"])
        self.assertEqual(stopped, ["a", "c"])
        self.assertIn("Failed to stop proxy session for channel b", logs.output[0])
