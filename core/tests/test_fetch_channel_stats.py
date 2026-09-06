"""The beat task that broadcasts channel_stats asks the relay.

It runs in the worker role, which has no nginx of its own and no access
to a relay-owned Redis key it has any business reading. A relay outage
must not push an empty stats payload: the Stats page clears its rows on
one, and a restarting relay is not an idle system.
"""

from unittest import mock

from django.test import TestCase

from apps.proxy import relay_client
from core import tasks


class FetchChannelStatsTests(TestCase):
    def test_the_payload_is_the_relay_s_channel_list(self):
        payload = {"channels": [{"channel_id": "abc"}], "count": 1}
        with mock.patch.object(
            relay_client, "list_channels", return_value=payload
        ), mock.patch.object(tasks, "send_websocket_update") as pushed:
            tasks.fetch_channel_stats()
        message = pushed.call_args.args[2]
        self.assertEqual(message["type"], "channel_stats")
        self.assertEqual(message["stats"], tasks.json.dumps(payload))

    def test_a_relay_outage_pushes_nothing_at_all(self):
        with mock.patch.object(
            relay_client, "list_channels",
            side_effect=relay_client.RelayUnavailable("down"),
        ), mock.patch.object(tasks, "send_websocket_update") as pushed:
            tasks.fetch_channel_stats()
        pushed.assert_not_called()

    def test_a_misconfigured_relay_also_pushes_nothing(self):
        # Final review round, minor: mirrors the RelayUnavailable test
        # above for the ImproperlyConfigured branch fetch_channel_stats
        # gained beside it.
        from django.core.exceptions import ImproperlyConfigured

        exc = ImproperlyConfigured("DISPATCHARR_RELAY_BASE_URL is bad")
        exc.var_name = "DISPATCHARR_RELAY_BASE_URL"
        with mock.patch.object(
            relay_client, "list_channels", side_effect=exc
        ), mock.patch.object(tasks, "send_websocket_update") as pushed:
            tasks.fetch_channel_stats()
        pushed.assert_not_called()

    def test_core_tasks_no_longer_imports_a_relay_module_at_module_level(self):
        import inspect

        source = inspect.getsource(tasks)
        header = source.split("def ", 1)[0]
        self.assertNotIn("apps.proxy.live_proxy", header)
