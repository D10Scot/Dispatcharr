"""The five IsAdmin views are wrappers now, and nothing else changed.

They keep their URLs, their permission class, their methods and their
JSON. What changed is where the answer comes from: relay_client instead
of a direct Redis read or an in-process ChannelService call. These tests
assert the mapping in both directions, including the two statuses that
are new because a relay that cannot be reached is a new thing to be.
"""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.proxy import relay_client
from apps.proxy.live_proxy import views


class AdminControlViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="p", user_level=User.UserLevel.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        # channel_status calls close_old_connections() in a finally block.
        # Under TestCase's class-level atomic wrapping (CONN_MAX_AGE=0),
        # closing here doesn't fully close the connection -- Django leaves
        # the wrapper pointing at the now-actually-closed psycopg
        # connection (BaseDatabaseWrapper.close()'s in_atomic_block
        # branch), so the next test's ORM call in setUp raises
        # psycopg.OperationalError. apps/proxy/live_proxy/tests/
        # test_live_db_cleanup.py hits the same landmine and patches this
        # call out; this test class does the same.
        patcher = mock.patch.object(views, "close_old_connections")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_collection_returns_the_relay_s_payload(self):
        payload = {"channels": [{"channel_id": "abc"}], "count": 1}
        with mock.patch.object(
            relay_client, "list_channels", return_value=payload
        ), mock.patch.object(views, "send_websocket_update") as pushed:
            response = self.client.get("/proxy/ts/status")
        self.assertEqual(response.json(), payload)
        # The broadcast is a side effect of polling this endpoint and
        # stays a side effect of polling this endpoint.
        self.assertEqual(pushed.call_args.args[2]["type"], "channel_stats")

    def test_status_detail_returns_the_relay_s_channel(self):
        with mock.patch.object(
            relay_client, "get_channel", return_value={"channel_id": "abc"}
        ):
            response = self.client.get("/proxy/ts/status/abc")
        self.assertEqual(response.json()["channel_id"], "abc")

    def test_status_detail_404s_for_a_channel_the_relay_does_not_hold(self):
        with mock.patch.object(relay_client, "get_channel", return_value=None):
            response = self.client.get("/proxy/ts/status/abc")
        self.assertEqual(response.status_code, 404)

    def test_an_unreachable_relay_is_503_not_500(self):
        with mock.patch.object(
            relay_client, "list_channels",
            side_effect=relay_client.RelayUnavailable("down"),
        ):
            response = self.client.get("/proxy/ts/status")
        self.assertEqual(response.status_code, 503)

    def test_a_refusing_relay_is_502(self):
        with mock.patch.object(
            relay_client, "get_channel",
            side_effect=relay_client.RelayRefused(403, "/proxy/relay/channels/abc"),
        ):
            response = self.client.get("/proxy/ts/status/abc")
        self.assertEqual(response.status_code, 502)

    def test_stop_channel_maps_the_service_error_to_404_as_before(self):
        with mock.patch.object(
            relay_client, "stop_channel",
            return_value={"status": "error", "message": "Channel not found"},
        ):
            response = self.client.post("/proxy/ts/stop/abc")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Channel not found")

    def test_stop_channel_reports_the_previous_state_as_before(self):
        with mock.patch.object(
            relay_client, "stop_channel",
            return_value={"status": "success", "previous_state": {"state": "active"}},
        ) as stopped:
            response = self.client.post("/proxy/ts/stop/abc")
        stopped.assert_called_once_with("abc")
        self.assertEqual(
            response.json(),
            {
                "message": "Channel stop request sent",
                "channel_id": "abc",
                "previous_state": {"state": "active"},
            },
        )

    def test_stop_client_requires_a_client_id_as_before(self):
        response = self.client.post(
            "/proxy/ts/stop_client/abc", data={}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_stop_client_passes_both_segments_through(self):
        with mock.patch.object(
            relay_client, "stop_client",
            return_value={"status": "success", "locally_processed": True},
        ) as stopped:
            response = self.client.post(
                "/proxy/ts/stop_client/abc",
                data={"client_id": "c1"},
                format="json",
            )
        stopped.assert_called_once_with("abc", "c1")
        self.assertEqual(response.json()["locally_processed"], True)

    def test_change_stream_resolves_in_django_and_applies_on_the_relay(self):
        source = {
            "url": "http://p/next",
            "user_agent": "d",
            "m3u_profile_id": 3,
            "stream_name": "Two",
        }
        with mock.patch(
            "apps.proxy.next_source.resolve_source",
            return_value={"source": source, "error": None},
        ), mock.patch.object(
            relay_client, "advance",
            return_value={"status": "success", "success": True, "direct_update": True},
        ) as advanced:
            response = self.client.post(
                "/proxy/ts/change_stream/abc",
                data={"stream_id": 42},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIs(advanced.call_args.kwargs["reset_tried"], True)
        self.assertEqual(advanced.call_args.kwargs["stream_id"], 42)
        self.assertEqual(response.json()["stream_id"], 42)

    def test_change_stream_still_rejects_a_non_integer_stream_id(self):
        response = self.client.post(
            "/proxy/ts/change_stream/abc",
            data={"stream_id": "not-a-number"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_change_stream_maps_an_unconfirmed_switch_to_504(self):
        with mock.patch.object(
            relay_client, "advance",
            return_value={
                "status": "success", "success": False, "confirmed": False,
                "message": "not confirmed",
            },
        ):
            response = self.client.post(
                "/proxy/ts/change_stream/abc",
                data={"url": "http://p/x"},
                format="json",
            )
        self.assertEqual(response.status_code, 504)

    def test_change_stream_maps_a_reported_failure_to_502(self):
        with mock.patch.object(
            relay_client, "advance",
            return_value={"status": "success", "success": False, "message": "no"},
        ):
            response = self.client.post(
                "/proxy/ts/change_stream/abc",
                data={"url": "http://p/x"},
                format="json",
            )
        self.assertEqual(response.status_code, 502)
