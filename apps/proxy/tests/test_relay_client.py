"""Django's side of the Django->relay boundary (Phase 1 PR 7, D9/D10).

The transport (RelayClientTransportTests) and the six call methods
(RelayClientCallTests) are both tested here, against a mocked
_request/requests.request -- so a literal path or query parameter is
asserted only against itself. test_relay_control_api.py's
RelayClientRoundTripTests drives the same six methods through the real
routes, which is what would catch a renamed query parameter or a path
encoding the two sides disagree on (Phase 1 PR 7 fix round 1).
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

    def test_only_the_transport_failure_is_marked_relay_wide(self):
        # Final review round: a 5xx, a redirect and a garbled 2xx body
        # are per-request outcomes from a relay that answered at least
        # once; only a requests.RequestException means the relay could
        # not be reached at all. stop_channels() uses this to decide
        # whether one failure justifies aborting the rest of a batch.
        with mock.patch.object(requests, "request", return_value=_Response(502)):
            try:
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
                self.fail("expected RelayUnavailable")
            except relay_client.RelayUnavailable as exc:
                self.assertFalse(exc.transport)
        with mock.patch.object(
            requests, "request", side_effect=requests.ConnectionError("nope")
        ):
            try:
                relay_client._request("GET", "/proxy/relay/channels", timeout=(1, 2))
                self.fail("expected RelayUnavailable")
            except relay_client.RelayUnavailable as exc:
                self.assertTrue(exc.transport)

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

    def test_a_transport_error_s_message_never_names_the_dialled_host(self):
        # requests.ConnectionError's own text carries host, port and the
        # full path+query (e.g. "HTTPConnectionPool(host='web', port=80):
        # Max retries exceeded with url: /proxy/relay/channels/<uuid>?
        # fields=state"). The global constraint says relay_client's log
        # lines name "the identifier and the status code only, never the
        # URL it dialled" -- so the raised message must not embed that
        # text (fix round 1, finding 3).
        base_url = relay_client.get_relay_control_base_url()
        with mock.patch.object(
            requests, "request",
            side_effect=requests.ConnectionError(
                f"HTTPConnectionPool(host='web', port=80): Max retries "
                f"exceeded with url: {base_url}/proxy/relay/channels"
            ),
        ):
            with self.assertLogs(relay_client.logger, level="WARNING") as caught:
                # channel_snapshot never raises (ruling 13): it logs and
                # returns an unreachable snapshot instead.
                relay_client.channel_snapshot("x")
        logged = "\n".join(caught.output)
        self.assertNotIn(base_url, logged)
        self.assertNotIn("host=", logged)
        self.assertNotIn("port=", logged)


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

    def test_an_identifier_is_encoded_the_way_django_will_reproduce_it(self):
        # escape_uri_path's safe set (what get_full_path() reconstructs a
        # path through, since nginx hands Django an already-decoded
        # PATH_INFO) keeps ':' unescaped; quote(..., safe='') would encode
        # it to %3A and sign a string the relay's own reconstruction never
        # produces, refusing every such call with 403 (fix round 1,
        # finding 1). A space is still not in that safe set, so it is
        # still percent-encoded either way.
        with mock.patch.object(relay_client, "_request", return_value={}) as sent:
            relay_client.get_channel("a:b")
        self.assertEqual(sent.call_args.args[1], "/proxy/relay/channels/a:b")
        with mock.patch.object(relay_client, "_request", return_value={}) as sent:
            relay_client.get_channel("c 1")
        self.assertEqual(sent.call_args.args[1], "/proxy/relay/channels/c%201")

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

    def test_a_misconfigured_relay_propagates_out_of_channel_snapshot(self):
        # Unlike RelayUnavailable/RelayRefused above, channel_snapshot's
        # except clause does not name ImproperlyConfigured: a misconfigured
        # deployment must fail visibly on the first tune (PR 6's Amendment
        # S10 point 5, mirrored here for the reverse direction), not be
        # swallowed into "the relay has nothing running."
        from django.core.exceptions import ImproperlyConfigured

        with mock.patch.object(
            relay_client, "_request",
            side_effect=ImproperlyConfigured("DISPATCHARR_RELAY_BASE_URL is bad"),
        ):
            with self.assertRaises(ImproperlyConfigured):
                relay_client.channel_snapshot("x")

    def test_stop_channels_never_raises_and_continues_past_a_refusal(self):
        # A RelayRefused (a 404 for a channel already stopped, say) is a
        # per-channel answer -- it says nothing about the rest -- so the
        # loop keeps going, same as before this bound existed.
        seen = []

        def _refuse_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                raise relay_client.RelayRefused(404, "/proxy/relay/channels/b")
            return {"status": "success"}

        with mock.patch.object(
            relay_client, "stop_channel", side_effect=_refuse_the_second
        ):
            stopped = relay_client.stop_channels(iter(["a", "b", "c"]))
        self.assertEqual(seen, ["a", "b", "c"])
        self.assertEqual(stopped, ["a", "c"])

    def test_stop_channels_stops_after_the_first_unreachable_relay(self):
        # Kimi's PR #194 review, question 2: a whole-provider M3U delete
        # can pass hundreds of identifiers. Once the relay itself cannot
        # be reached at all (a connection-level failure, transport=True),
        # every remaining identifier would pay the same round trip and
        # fail the same way, so the loop stops on the first one rather
        # than visiting the rest, and reports what it actually stopped.
        seen = []

        def _unreachable_on_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                raise relay_client.RelayUnavailable("down", transport=True)
            return {"status": "success"}

        with mock.patch.object(
            relay_client, "stop_channel", side_effect=_unreachable_on_the_second
        ):
            with self.assertLogs(relay_client.logger, level="WARNING") as caught:
                stopped = relay_client.stop_channels(iter(["a", "b", "c", "d"]))
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(stopped, ["a"])
        self.assertEqual(len(caught.output), 1)

    def test_stop_channels_continues_past_a_per_request_relay_unavailable(self):
        # Final review round: RelayUnavailable is also raised for a
        # redirect, a 5xx or a garbled 2xx body -- per-request outcomes
        # from a relay that DID answer (a single stuck channel past
        # ADMIN_TIMEOUT, one worker recycle). Aborting the whole batch
        # over one of those would strand channels that would have
        # stopped fine; transport=False (the default) keeps the loop
        # going, same as a RelayRefused.
        seen = []

        def _garbled_on_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                raise relay_client.RelayUnavailable(
                    "/proxy/relay/channels/b answered 2xx with a non-JSON body"
                )
            return {"status": "success"}

        with mock.patch.object(
            relay_client, "stop_channel", side_effect=_garbled_on_the_second
        ):
            stopped = relay_client.stop_channels(iter(["a", "b", "c"]))
        self.assertEqual(seen, ["a", "b", "c"])
        self.assertEqual(stopped, ["a", "c"])

    def test_stop_channels_stops_after_a_misconfigured_relay(self):
        # Same bound as RelayUnavailable: a misconfigured base URL fails
        # identically for every remaining identifier.
        from django.core.exceptions import ImproperlyConfigured

        seen = []

        def _misconfigured_on_the_second(identifier, **kwargs):
            seen.append(identifier)
            if identifier == "b":
                exc = ImproperlyConfigured("bad url")
                exc.var_name = "DISPATCHARR_RELAY_BASE_URL"
                raise exc
            return {"status": "success"}

        with mock.patch.object(
            relay_client, "stop_channel", side_effect=_misconfigured_on_the_second
        ):
            with self.assertLogs(relay_client.logger, level="WARNING") as caught:
                stopped = relay_client.stop_channels(iter(["a", "b", "c"]))
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(stopped, ["a"])
        self.assertIn("DISPATCHARR_RELAY_BASE_URL", caught.output[0])

    def test_stop_channels_skips_a_falsy_identifier(self):
        with mock.patch.object(
            relay_client, "stop_channel", return_value={"status": "success"}
        ) as stopped:
            result = relay_client.stop_channels([None, "", "a"])
        self.assertEqual(stopped.call_count, 1)
        self.assertEqual(result, ["a"])

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
