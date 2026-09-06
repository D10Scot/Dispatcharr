"""Django's side of the Django->relay boundary (Phase 1 PR 7, D9/D10).

Only the transport here; the five call methods are tested in
test_relay_control_api.py against the real routes.
"""

import os
from unittest import mock

import requests
from django.test import SimpleTestCase

from apps.proxy import internal_auth, relay_client


class _Response:
    def __init__(self, status_code, body=b"{}", json_value=mock.sentinel.use_body):
        self.status_code = status_code
        self.content = body
        self._json = json_value

    def json(self):
        if self._json is mock.sentinel.use_body:
            import json as _json

            return _json.loads(self.content)
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class RelayClientTransportTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict(
            os.environ, {"DISPATCHARR_ENV": "aio"}, clear=True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_call_carries_both_internal_headers(self):
        with mock.patch.object(
            requests, "request", return_value=_Response(200)
        ) as sent:
            relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
        headers = sent.call_args.kwargs["headers"]
        self.assertEqual(
            headers[internal_auth.HEADER_INTERNAL],
            internal_auth.internal_principal_token(),
        )
        self.assertTrue(
            headers[internal_auth.HEADER_INTERNAL_REQUEST].startswith("v1.")
        )

    def test_the_signature_covers_the_query_string(self):
        with mock.patch.object(
            requests, "request", return_value=_Response(200)
        ) as sent:
            relay_client._request(
                "GET",
                "/proxy/relay/channels",
                timeout=(1, 2),
                params={"clients": "all"},
            )
        url = sent.call_args.args[1]
        self.assertTrue(url.endswith("/proxy/relay/channels?clients=all"))
        header = sent.call_args.kwargs["headers"][
            internal_auth.HEADER_INTERNAL_REQUEST
        ]
        _v, timestamp, digest = header.split(".")
        self.assertEqual(
            digest,
            internal_auth.internal_request_token(
                "GET", "/proxy/relay/channels?clients=all", b"", int(timestamp)
            ),
        )

    def test_a_redirect_is_never_followed(self):
        with mock.patch.object(
            requests, "request", return_value=_Response(301)
        ) as sent:
            with self.assertRaises(relay_client.RelayUnavailable):
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
        self.assertIs(sent.call_args.kwargs["allow_redirects"], False)

    def test_a_4xx_is_a_refusal_not_an_outage(self):
        with mock.patch.object(requests, "request", return_value=_Response(403)):
            with self.assertRaises(relay_client.RelayRefused) as caught:
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIsInstance(
            caught.exception, relay_client.RelayUnavailable
        )

    def test_a_5xx_and_a_transport_error_are_both_outages(self):
        with mock.patch.object(requests, "request", return_value=_Response(502)):
            with self.assertRaises(relay_client.RelayUnavailable):
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
        with mock.patch.object(
            requests, "request", side_effect=requests.ConnectionError("nope")
        ):
            with self.assertRaises(relay_client.RelayUnavailable):
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))

    def test_nothing_is_retried(self):
        # A retried advance switches twice; a retried tune-path read
        # blows the relay's own 5s next-source budget (ruling 13).
        with mock.patch.object(
            requests, "request", side_effect=requests.ConnectionError("nope")
        ) as sent:
            with self.assertRaises(relay_client.RelayUnavailable):
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
        self.assertEqual(sent.call_count, 1)

    def test_a_2xx_that_is_not_a_json_object_is_an_outage(self):
        for body in (_Response(200, json_value=ValueError("no")), _Response(200, json_value=[1])):
            with mock.patch.object(requests, "request", return_value=body):
                with self.assertRaises(relay_client.RelayUnavailable):
                    relay_client._request(
                        "GET", "/proxy/relay/channels", timeout=(1, 2)
                    )

    def test_an_empty_body_is_an_empty_dict_not_an_error(self):
        with mock.patch.object(
            requests, "request", return_value=_Response(204, body=b"")
        ):
            self.assertEqual(
                relay_client._request(
                    "DELETE", "/proxy/relay/channels/x", timeout=(2, 5)
                ),
                {},
            )

    def test_the_three_timeout_budgets_are_named_constants(self):
        self.assertEqual(relay_client.TUNE_TIMEOUT, (1, 2))
        self.assertEqual(relay_client.ADMIN_TIMEOUT, (2, 5))
        # 15s is STREAM_SWITCH_CONFIRM_TIMEOUT in ChannelService.
        self.assertGreater(relay_client.ADVANCE_TIMEOUT[1], 15)


class RelayClientCallTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict(
            os.environ, {"DISPATCHARR_ENV": "aio"}, clear=True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_channels_asks_for_every_client_only_when_told_to(self):
        with mock.patch.object(
            relay_client, "_request", return_value={"channels": [], "count": 0}
        ) as sent:
            relay_client.list_channels()
            self.assertIsNone(sent.call_args.kwargs["params"])
            relay_client.list_channels(all_clients=True)
            self.assertEqual(
                sent.call_args.kwargs["params"], {"clients": "all"}
            )

    def test_get_channel_turns_the_relay_s_404_into_none(self):
        with mock.patch.object(
            relay_client,
            "_request",
            side_effect=relay_client.RelayRefused(404, "/proxy/relay/channels/x"),
        ):
            self.assertIsNone(relay_client.get_channel("x"))

    def test_get_channel_re_raises_every_other_refusal(self):
        with mock.patch.object(
            relay_client,
            "_request",
            side_effect=relay_client.RelayRefused(403, "/proxy/relay/channels/x"),
        ):
            with self.assertRaises(relay_client.RelayRefused):
                relay_client.get_channel("x")

    def test_an_identifier_is_percent_encoded_into_the_path(self):
        with mock.patch.object(relay_client, "_request", return_value={}) as sent:
            relay_client.get_channel("a/b")
        self.assertEqual(sent.call_args.args[1], "/proxy/relay/channels/a%2Fb")

    def test_channel_snapshot_reports_present_and_active(self):
        with mock.patch.object(
            relay_client, "_request", return_value={"state": "active"}
        ):
            snapshot = relay_client.channel_snapshot("x")
        self.assertEqual((snapshot.present, snapshot.active, snapshot.reachable),
                         (True, True, True))

    def test_channel_snapshot_calls_a_stopping_channel_present_but_inactive(self):
        with mock.patch.object(
            relay_client, "_request", return_value={"state": "stopping"}
        ):
            snapshot = relay_client.channel_snapshot("x")
        self.assertEqual((snapshot.present, snapshot.active), (True, False))

    def test_channel_snapshot_uses_the_tune_budget_and_the_narrow_form(self):
        with mock.patch.object(relay_client, "_request", return_value={}) as sent:
            relay_client.channel_snapshot("x")
        self.assertEqual(sent.call_args.kwargs["timeout"], relay_client.TUNE_TIMEOUT)
        # Ruling 20: one EXISTS + one HGET on the relay, not the full
        # diagnostic walk, under a two-second budget.
        self.assertEqual(sent.call_args.kwargs["params"], {"fields": "state"})

    def test_an_unreachable_relay_is_a_snapshot_not_an_exception(self):
        # get_stream()'s reuse branch runs inside the relay's own
        # next-source call; raising here would turn a relay hiccup into
        # a failed tune (ruling 13).
        with mock.patch.object(
            relay_client, "_request",
            side_effect=relay_client.RelayUnavailable("down"),
        ):
            snapshot = relay_client.channel_snapshot("x")
        self.assertEqual((snapshot.present, snapshot.active, snapshot.reachable),
                         (False, False, False))

    def test_stop_channels_never_raises_and_visits_every_identifier(self):
        seen = []

        def _fail_on_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                raise relay_client.RelayUnavailable("down")
            return {"status": "success"}

        with mock.patch.object(
            relay_client, "stop_channel", side_effect=_fail_on_the_second
        ):
            relay_client.stop_channels(iter(["a", "b", "c"]))
        self.assertEqual(seen, ["a", "b", "c"])

    def test_stop_channels_skips_a_falsy_identifier(self):
        with mock.patch.object(
            relay_client, "stop_channel", return_value={"status": "success"}
        ) as stopped:
            relay_client.stop_channels([None, "", "a"])
        self.assertEqual(stopped.call_count, 1)

    def test_advance_sends_the_resolved_source_and_the_long_budget(self):
        with mock.patch.object(
            relay_client, "_request", return_value={"status": "success"}
        ) as sent:
            relay_client.advance(
                "abc",
                url="http://p/next",
                user_agent="d",
                stream_id=42,
                m3u_profile_id=3,
                stream_name="Two",
                reset_tried=True,
            )
        self.assertEqual(sent.call_args.args, ("POST", "/proxy/relay/channels/abc/advance"))
        self.assertEqual(
            sent.call_args.kwargs["payload"],
            {
                "url": "http://p/next",
                "user_agent": "d",
                "stream_id": 42,
                "m3u_profile_id": 3,
                "stream_name": "Two",
                "reset_tried": True,
            },
        )
        self.assertEqual(
            sent.call_args.kwargs["timeout"], relay_client.ADVANCE_TIMEOUT
        )

    def test_stop_client_encodes_both_segments(self):
        with mock.patch.object(relay_client, "_request", return_value={}) as sent:
            relay_client.stop_client("abc", "c 1")
        self.assertEqual(
            sent.call_args.args[1], "/proxy/relay/channels/abc/clients/c%201"
        )
