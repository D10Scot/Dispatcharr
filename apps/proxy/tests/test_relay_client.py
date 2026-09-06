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
