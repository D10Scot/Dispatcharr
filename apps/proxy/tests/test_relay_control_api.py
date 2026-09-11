"""The five /proxy/relay/... routes (Phase 1 PR 7, D12).

Served by the relay process, gated by IsInternalRelay -- the two internal
HMAC headers, never a principal. nginx routes them to the relay_py
upstream and adds nothing: the token is the whole gate (D9), and the
location is deliberately outside the authorize hop, since
authorize_stream() would 404 a URI naming no channel (spec Amendment S8).
"""

import json
import os
from unittest import mock
from urllib.parse import urlsplit

import requests
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.proxy import relay_client, relay_views
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)


def _signed(method, path, body=b""):
    return {
        "HTTP_X_DISPATCHARR_INTERNAL": internal_principal_token(),
        "HTTP_X_DISPATCHARR_INTERNAL_REQUEST": build_internal_request_header(
            method, path, body
        ),
    }


# The Django META names for the two headers relay_client._request signs
# every call with -- reused rather than re-derived so the round trip below
# carries exactly what relay_client sends, nothing guessed from a naming
# convention.
_HEADER_TO_META = {
    HEADER_INTERNAL: "HTTP_X_DISPATCHARR_INTERNAL",
    HEADER_INTERNAL_REQUEST: "HTTP_X_DISPATCHARR_INTERNAL_REQUEST",
}


class RelayControlGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_an_unsigned_request_is_refused(self):
        self.assertEqual(self.client.get("/proxy/relay/channels").status_code, 403)

    def test_the_static_token_alone_is_not_enough(self):
        response = self.client.get(
            "/proxy/relay/channels",
            HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token(),
        )
        self.assertEqual(response.status_code, 403)

    def test_an_admin_session_is_not_a_way_in(self):
        admin = User.objects.create_user(
            username="a", password="p", user_level=User.UserLevel.ADMIN
        )
        self.client.force_authenticate(user=admin)
        self.assertEqual(self.client.get("/proxy/relay/channels").status_code, 403)

    def test_a_signature_for_a_different_path_does_not_open_this_one(self):
        headers = _signed("GET", "/proxy/relay/channels/other")
        self.assertEqual(
            self.client.get("/proxy/relay/channels", **headers).status_code, 403
        )

    def test_a_correctly_signed_request_is_admitted(self):
        # ProxyServer.get_instance() is patched here and in every list
        # test below: channels_view reaches it for the Redis client, and
        # leaving it unpatched builds a real singleton that outlives the
        # test. The advance tests already patch it for the same reason.
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [], "count": 0},
        ), mock.patch.object(
            relay_views.ProxyServer, "get_instance",
            return_value=mock.Mock(redis_client=mock.Mock(), stream_managers={}),
        ):
            response = self.client.get(
                "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
            )
        self.assertEqual(response.status_code, 200)


class RelayChannelListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        patcher = mock.patch.object(
            relay_views.ProxyServer, "get_instance",
            return_value=mock.Mock(redis_client=mock.Mock(), stream_managers={}),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _channel(self, **overrides):
        data = {
            "channel_id": "abc",
            "state": "active",
            "url": "http://provider.example/live",
            "stream_profile": "3",
            "owner": "worker-1",
            "buffer_index": 7,
            "client_count": 2,
            "uptime": 12.5,
            "started_at": 1000.0,
            "clients": [
                {
                    "client_id": "c1",
                    "user_agent": "vlc",
                    "output_format": "mpegts",
                    "output_profile_id": None,
                    "user_id": "5",
                    "connected_at": 1000.0,
                    "ip_address": "10.0.0.1",
                }
            ],
        }
        data.update(overrides)
        return data

    def test_the_payload_is_channels_and_count(self):
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [self._channel()], "count": 1},
        ):
            response = self.client.get(
                "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
            )
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["channels"][0]["channel_id"], "abc")
        self.assertEqual(body["channels"][0]["clients"][0]["client_id"], "c1")

    def test_an_absent_optional_field_stays_absent_rather_than_null(self):
        # stream_id and avg_bitrate_kbps are assigned inside conditionals
        # in get_basic_channel_info, so the wire has to be able to omit
        # them -- CLAUDE.md section Observing a channel.
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [self._channel()], "count": 1},
        ):
            response = self.client.get(
                "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
            )
        channel = response.json()["channels"][0]
        self.assertNotIn("stream_id", channel)
        self.assertNotIn("avg_bitrate_kbps", channel)

    def test_clients_all_asks_for_an_uncapped_client_list(self):
        path = "/proxy/relay/channels?clients=all"
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [], "count": 0},
        ) as built:
            response = self.client.get(path, **_signed("GET", path))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(built.call_args.kwargs["client_limit"])

    def test_the_default_keeps_the_stats_cap(self):
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [], "count": 0},
        ) as built:
            self.client.get(
                "/proxy/relay/channels", **_signed("GET", "/proxy/relay/channels")
            )
        self.assertEqual(built.call_args.kwargs["client_limit"], 10)


class RelayChannelDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_a_known_channel_returns_its_detailed_info(self):
        path = "/proxy/relay/channels/abc"
        with mock.patch.object(
            relay_views.ChannelStatus, "get_detailed_channel_info",
            return_value={
                "channel_id": "abc",
                "state": None,
                "url": "",
                "stream_profile": "",
                "owner": "unknown",
                "buffer_index": 0,
                "clients": [],
                "client_count": 0,
                "buffer_stats": {"chunks": 0, "diagnostics": {}},
                "ffmpeg_speed": 1.02,
                "width": "1920",
            },
        ):
            response = self.client.get(path, **_signed("GET", path))
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["state"])
        self.assertEqual(body["ffmpeg_speed"], 1.02)
        self.assertEqual(body["width"], "1920")

    def test_an_unknown_channel_is_a_404(self):
        path = "/proxy/relay/channels/nope"
        with mock.patch.object(
            relay_views.ChannelStatus, "get_detailed_channel_info", return_value=None
        ):
            response = self.client.get(path, **_signed("GET", path))
        self.assertEqual(response.status_code, 404)

    def test_fields_state_answers_from_two_redis_calls_and_no_detail_walk(self):
        # Ruling 20: the tune path asks one question, so it must not pay
        # for buffer-chunk sampling and two ORM name fallbacks. The
        # exact-equality assertion is the point -- it is what fails if
        # the branch ever renders through RelayChannelDetailSerializer,
        # whose four allow_null fields would add url/stream_profile/
        # owner as nulls this answer knows nothing about.
        path = "/proxy/relay/channels/abc?fields=state"
        redis = mock.Mock()
        redis.exists.return_value = 1
        redis.hget.return_value = "active"
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance",
            return_value=mock.Mock(redis_client=redis),
        ), mock.patch.object(
            relay_views.ChannelStatus, "get_detailed_channel_info"
        ) as detailed:
            response = self.client.get(path, **_signed("GET", path))
        detailed.assert_not_called()
        self.assertEqual(
            response.json(), {"channel_id": "abc", "state": "active"}
        )

    def test_fields_state_404s_when_the_relay_holds_no_metadata(self):
        path = "/proxy/relay/channels/abc?fields=state"
        redis = mock.Mock()
        redis.exists.return_value = 0
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance",
            return_value=mock.Mock(redis_client=redis),
        ):
            response = self.client.get(path, **_signed("GET", path))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(), {"channel_id": "abc", "state": None}
        )

    def test_delete_stops_the_channel(self):
        path = "/proxy/relay/channels/abc"
        with mock.patch.object(
            relay_views.ChannelService, "stop_channel",
            return_value={"status": "success", "previous_state": {"state": "active"}},
        ) as stopped:
            response = self.client.delete(path, **_signed("DELETE", path))
        stopped.assert_called_once_with("abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_delete_reports_the_relay_s_own_not_found(self):
        path = "/proxy/relay/channels/abc"
        with mock.patch.object(
            relay_views.ChannelService, "stop_channel",
            return_value={"status": "error", "message": "Channel not found"},
        ):
            response = self.client.delete(path, **_signed("DELETE", path))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "error")
        self.assertEqual(response.json()["message"], "Channel not found")


class RelayClientAndAdvanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_deleting_a_client_calls_stop_client(self):
        path = "/proxy/relay/channels/abc/clients/c1"
        with mock.patch.object(
            relay_views.ChannelService, "stop_client",
            return_value={"status": "success", "locally_processed": True},
        ) as stopped:
            response = self.client.delete(path, **_signed("DELETE", path))
        stopped.assert_called_once_with("abc", "c1")
        self.assertEqual(response.json()["locally_processed"], True)

    def test_advance_passes_a_fully_resolved_source_through(self):
        # Ruling 11: the relay resolves nothing. new_url is always
        # present, so change_stream_url never takes its next_source
        # branch from here.
        path = "/proxy/relay/channels/abc/advance"
        payload = {
            "stream_id": 42,
            "url": "http://provider.example/next",
            "user_agent": "Dispatcharr",
            "m3u_profile_id": 3,
            "stream_name": "Two",
        }
        body = json.dumps(payload).encode()
        with mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={"status": "success", "success": True, "direct_update": True},
        ) as changed:
            response = self.client.post(
                path, data=body, content_type="application/json",
                **_signed("POST", path, body),
            )
        changed.assert_called_once_with(
            "abc",
            "http://provider.example/next",
            "Dispatcharr",
            42,
            3,
            stream_name="Two",
            channel_name=None,
            m3u_profile_name=None,
        )
        self.assertEqual(response.json()["success"], True)

    def test_advance_passes_channel_name_and_m3u_profile_name_through(self):
        """PIN. Phase 2 PR 2b-1: the prior test always sends None for both
        of these, which passes trivially whether or not the route actually
        threads them through -- this sends real values on the wire."""
        path = "/proxy/relay/channels/abc/advance"
        payload = {
            "stream_id": 42,
            "url": "http://provider.example/next",
            "user_agent": "Dispatcharr",
            "m3u_profile_id": 3,
            "stream_name": "Two",
            "channel_name": "BBC Two",
            "m3u_profile_name": "Provider A default",
        }
        body = json.dumps(payload).encode()
        with mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={"status": "success", "success": True, "direct_update": True},
        ) as changed:
            response = self.client.post(
                path, data=body, content_type="application/json",
                **_signed("POST", path, body),
            )
        changed.assert_called_once_with(
            "abc",
            "http://provider.example/next",
            "Dispatcharr",
            42,
            3,
            stream_name="Two",
            channel_name="BBC Two",
            m3u_profile_name="Provider A default",
        )
        self.assertEqual(response.json()["success"], True)

    def test_advance_requires_a_url(self):
        path = "/proxy/relay/channels/abc/advance"
        body = json.dumps({"stream_id": 42}).encode()
        response = self.client.post(
            path, data=body, content_type="application/json",
            **_signed("POST", path, body),
        )
        self.assertEqual(response.status_code, 400)

    def test_advance_reports_an_unconfirmed_switch_without_inventing_a_status(self):
        path = "/proxy/relay/channels/abc/advance"
        payload = {"stream_id": 42, "url": "http://p/x", "user_agent": "d"}
        body = json.dumps(payload).encode()
        with mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={
                "status": "success", "success": False, "confirmed": False,
                "message": "not confirmed", "direct_update": False,
            },
        ):
            response = self.client.post(
                path, data=body, content_type="application/json",
                **_signed("POST", path, body),
            )
        body_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIs(body_json["success"], False)
        self.assertIs(body_json["confirmed"], False)

    def test_reset_tried_clears_the_local_manager_s_exclusion_list(self):
        path = "/proxy/relay/channels/abc/advance"
        payload = {"url": "http://p/x", "stream_id": 42, "reset_tried": True}
        body = json.dumps(payload).encode()
        manager = mock.Mock(tried_stream_ids={1, 2})
        server = mock.Mock(stream_managers={"abc": manager})
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance", return_value=server
        ), mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={"status": "success", "success": True},
        ):
            self.client.post(
                path, data=body, content_type="application/json",
                **_signed("POST", path, body),
            )
        self.assertEqual(manager.tried_stream_ids, set())

    def test_reset_tried_is_off_by_default(self):
        path = "/proxy/relay/channels/abc/advance"
        payload = {"url": "http://p/x", "stream_id": 42}
        body = json.dumps(payload).encode()
        manager = mock.Mock(tried_stream_ids={1, 2})
        server = mock.Mock(stream_managers={"abc": manager})
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance", return_value=server
        ), mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={"status": "success", "success": True},
        ):
            self.client.post(
                path, data=body, content_type="application/json",
                **_signed("POST", path, body),
            )
        self.assertEqual(manager.tried_stream_ids, {1, 2})


class _FakeTransportResponse:
    """Adapts a Django test-client response to what relay_client._request
    reads off `requests.request`'s return value: .status_code, .content
    and .json()."""

    def __init__(self, django_response):
        self.status_code = django_response.status_code
        self.content = django_response.content

    def json(self):
        return json.loads(self.content)


class RelayClientRoundTripTests(TestCase):
    """Drives relay_client's six call methods through the real
    /proxy/relay/... routes, with requests.request patched to an adapter
    over APIClient rather than mocked away.

    Every other test class exercises one side of this boundary against
    itself: RelayClientCallTests (test_relay_client.py) mocks
    relay_client._request, so the client's own literals -- the path, the
    query parameters, the body shape -- are asserted only against
    themselves; the classes above mock ChannelService/ProxyServer, so the
    server's literals are asserted only against themselves. A renamed
    query parameter or a path-encoding mismatch between the two sides
    (fix round 1, findings 1 and 2) would pass every test in both files
    and only fail here, where the client's own signed request is what
    reaches the real view.
    """

    def setUp(self):
        self.client = APIClient()
        env_patcher = mock.patch.dict(
            os.environ, {"DISPATCHARR_ENV": "aio"}, clear=True
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        def fake_request(
            method, url, *, data=None, headers=None, timeout=None,
            allow_redirects=None,
        ):
            # Mirrors what nginx's location table hands the relay_py
            # upstream: PATH_INFO plus the query string, decoded, with
            # the two internal headers carried through unchanged.
            parsed = urlsplit(url)
            path = parsed.path
            if parsed.query:
                path = f"{path}?{parsed.query}"
            extra = {
                meta: (headers or {})[header]
                for header, meta in _HEADER_TO_META.items()
                if header in (headers or {})
            }
            call = getattr(self.client, method.lower())
            if data:
                response = call(
                    path, data=data, content_type="application/json", **extra
                )
            else:
                response = call(path, **extra)
            return _FakeTransportResponse(response)

        transport_patcher = mock.patch.object(
            requests, "request", side_effect=fake_request
        )
        transport_patcher.start()
        self.addCleanup(transport_patcher.stop)

    def test_channel_snapshot_reaches_the_real_view_and_reports_present(self):
        server = mock.Mock(redis_client=mock.Mock())
        server.redis_client.exists.return_value = True
        server.redis_client.hget.return_value = "active"
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance", return_value=server
        ):
            snapshot = relay_client.channel_snapshot("abc")
        self.assertEqual(
            (snapshot.present, snapshot.active, snapshot.reachable),
            (True, True, True),
        )

    def test_channel_snapshot_reaches_the_real_view_and_reports_absent(self):
        server = mock.Mock(redis_client=mock.Mock())
        server.redis_client.exists.return_value = False
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance", return_value=server
        ):
            snapshot = relay_client.channel_snapshot("abc")
        self.assertEqual(
            (snapshot.present, snapshot.active, snapshot.reachable),
            (False, False, True),
        )

    def test_channel_snapshot_reports_unreachable_on_a_real_gate_refusal(self):
        # A real 403 from IsInternalRelay, not a mocked RelayRefused: this
        # is what would have caught fix round 1's finding 1 -- a path
        # encoding mismatch between the client and get_full_path() also
        # surfaces as a 403 here, indistinguishable from this one.
        with mock.patch.object(
            relay_views.IsInternalRelay, "has_permission", return_value=False
        ):
            snapshot = relay_client.channel_snapshot("abc")
        self.assertEqual(
            (snapshot.present, snapshot.active, snapshot.reachable),
            (False, False, False),
        )

    def test_list_channels_all_clients_reaches_the_view_with_no_limit(self):
        with mock.patch.object(
            relay_views, "build_live_channel_stats_data",
            return_value={"channels": [], "count": 0},
        ) as built, mock.patch.object(
            relay_views.ProxyServer, "get_instance",
            return_value=mock.Mock(redis_client=mock.Mock()),
        ):
            result = relay_client.list_channels(all_clients=True)
        self.assertEqual(result, {"channels": [], "count": 0})
        self.assertIsNone(built.call_args.kwargs["client_limit"])

    def test_stop_client_reaches_the_real_view(self):
        with mock.patch.object(
            relay_views.ChannelService, "stop_client",
            return_value={"status": "success", "locally_processed": True},
        ) as stopped:
            result = relay_client.stop_client("abc", "c 1")
        stopped.assert_called_once_with("abc", "c 1")
        self.assertEqual(result["locally_processed"], True)

    def test_advance_reset_tried_reaches_the_real_view_and_clears_it(self):
        manager = mock.Mock(tried_stream_ids={1, 2})
        server = mock.Mock(stream_managers={"abc": manager})
        with mock.patch.object(
            relay_views.ProxyServer, "get_instance", return_value=server
        ), mock.patch.object(
            relay_views.ChannelService, "change_stream_url",
            return_value={"status": "success", "success": True},
        ) as changed:
            result = relay_client.advance(
                "abc", url="http://p/x", stream_id=42, reset_tried=True
            )
        changed.assert_called_once_with(
            "abc", "http://p/x", None, 42, None, stream_name=None,
            channel_name=None, m3u_profile_name=None,
        )
        self.assertEqual(manager.tried_stream_ids, set())
        self.assertEqual(result["success"], True)


class RelaySchemaTests(TestCase):
    def test_the_five_routes_appear_in_the_openapi_schema(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        for path in (
            "/proxy/relay/channels",
            "/proxy/relay/channels/{identifier}",
            "/proxy/relay/channels/{identifier}/clients/{client_id}",
            "/proxy/relay/channels/{identifier}/advance",
        ):
            self.assertIn(path, schema["paths"])
        detail = schema["paths"]["/proxy/relay/channels/{identifier}"]
        self.assertIn("get", detail)
        self.assertIn("delete", detail)
