"""Stopping DVR clients no longer scans the relay's client keys.

Both blocks used RedisKeys.clients / RedisKeys.client_metadata directly.
They now read GET /proxy/relay/channels/<uuid>, whose detailed payload
carries every client and every client's user_agent -- which is what the
"Dispatcharr-DVR" match needs.
"""

from unittest import mock

from django.test import TestCase

from apps.channels import api_views
from apps.proxy import relay_client


def _channel(clients):
    return {"channel_id": "abc", "client_count": len(clients), "clients": clients}


class StopDvrClientsTests(TestCase):
    def test_only_dvr_clients_are_stopped(self):
        payload = _channel([
            {"client_id": "c1", "user_agent": "Dispatcharr-DVR/recording-7"},
            {"client_id": "c2", "user_agent": "VLC/3.0"},
        ])
        with mock.patch.object(
            relay_client, "get_channel", return_value=payload
        ), mock.patch.object(
            relay_client, "stop_client", return_value={"status": "success"}
        ) as stopped:
            count = api_views._stop_dvr_clients("abc")
        self.assertEqual(count, 1)
        stopped.assert_called_once_with("abc", "c1")

    def test_a_recording_id_narrows_the_match(self):
        payload = _channel([
            {"client_id": "c1", "user_agent": "Dispatcharr-DVR/recording-7"},
            {"client_id": "c2", "user_agent": "Dispatcharr-DVR/recording-8"},
        ])
        with mock.patch.object(
            relay_client, "get_channel", return_value=payload
        ), mock.patch.object(
            relay_client, "stop_client", return_value={"status": "success"}
        ) as stopped:
            count = api_views._stop_dvr_clients("abc", recording_id=8)
        self.assertEqual(count, 1)
        stopped.assert_called_once_with("abc", "c2")

    def test_a_channel_the_relay_does_not_hold_stops_nothing(self):
        with mock.patch.object(
            relay_client, "get_channel", return_value=None
        ), mock.patch.object(relay_client, "stop_client") as stopped:
            self.assertEqual(api_views._stop_dvr_clients("abc"), 0)
        stopped.assert_not_called()

    def test_an_unreachable_relay_stops_nothing_and_does_not_raise(self):
        with mock.patch.object(
            relay_client, "get_channel",
            side_effect=relay_client.RelayUnavailable("down"),
        ):
            self.assertEqual(api_views._stop_dvr_clients("abc"), 0)

    def test_a_misconfigured_relay_also_stops_nothing_and_does_not_raise(self):
        # Final review round, minor: mirrors the RelayUnavailable test
        # above for the ImproperlyConfigured branch _stop_dvr_clients
        # gained beside it.
        from django.core.exceptions import ImproperlyConfigured

        exc = ImproperlyConfigured("DISPATCHARR_RELAY_BASE_URL is bad")
        exc.var_name = "DISPATCHARR_RELAY_BASE_URL"
        with mock.patch.object(relay_client, "get_channel", side_effect=exc):
            self.assertEqual(api_views._stop_dvr_clients("abc"), 0)
