"""The three /api/relay/... routes (Phase 1 PR 6, Task 6, D12).

Gated only by IsInternalRelay -- both internal headers, never a DRF or
session principal. These tests build the headers with the same helper
shape control_plane._post signs with, so a passing test here is proof the
relay's real client can talk to these routes.
"""

import json
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.internal_auth import build_internal_request_header, internal_principal_token
from core.models import StreamProfile, SystemEvent


class FakeRelayApiRedis:
    """Covers channel_stream, stream_profile and profile_connections --
    the same surface FakeControlPlaneRedis covers in
    test_next_source_resolution.py, reused here at the view layer."""

    def __init__(self):
        self._strings = {}
        self._hashes = {}

    def get(self, key):
        value = self._strings.get(key)
        if value is None:
            return None
        return str(value).encode()

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def delete(self, key):
        self._strings.pop(key, None)

    def exists(self, key):
        return key in self._strings

    def hget(self, key, field):
        # No metadata hash is ever seeded in these tests: every Channel
        # looks like it has no metadata fallback available, which matches
        # the between-get_stream()-and-initialize_channel() window release
        # via the primary channel_stream/stream_profile keys covers.
        return self._hashes.get(key, {}).get(field)

    def hdel(self, key, *fields):
        # release_stream() clears metadata fields unconditionally after a
        # successful release; a real Redis client accepts hdel on a key
        # with no such fields (and even a nonexistent key) without error.
        bucket = self._hashes.get(key)
        if not bucket:
            return
        for field in fields:
            bucket.pop(field, None)

    def incr(self, key):
        current = int(self._strings.get(key, 0) or 0) + 1
        self._strings[key] = current
        return current

    def decr(self, key):
        current = int(self._strings.get(key, 0) or 0) - 1
        self._strings[key] = current
        return current

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self._ops = []

    def decr(self, key):
        self._ops.append(("decr", key))
        return self

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def set(self, key, value):
        self._ops.append(("set", key, value))
        return self

    def execute(self):
        ops, self._ops = self._ops, []
        for op, *args in ops:
            getattr(self.redis, op)(*args)


class RelayApiTestCase(TestCase):
    """Fixture and signing helper shared by every route test."""

    def setUp(self):
        self.redis = FakeRelayApiRedis()
        self.redis_patcher = patch(
            "core.utils.RedisClient.get_client", return_value=self.redis
        )
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)

        # next_source.py's moved helpers close the DB connection in a
        # `finally` unconditionally; under CONN_MAX_AGE=0 that closes the
        # real connection a TestCase needs to keep open for its own
        # transaction. Patched out here, same as
        # test_next_source_resolution.py, so a test can call more than one
        # route per test.
        self.close_patcher = patch("apps.proxy.next_source.close_old_connections")
        self.close_patcher.start()
        self.addCleanup(self.close_patcher.stop)

        self.stream_profile_obj = StreamProfile.objects.create(
            name="pr6-relay-api-profile",
            command="ffmpeg",
            parameters="-i {streamUrl}",
        )
        self.account = M3UAccount.objects.create(
            name="pr6-relay-api-account",
            account_type="STD",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.m3u_profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.stream_a = Stream.objects.create(
            name="Relay API Stream A",
            url="http://example.com/relay-api-a.ts",
            m3u_account=self.account,
            stream_profile=self.stream_profile_obj,
            stream_hash="pr6-relay-api-hash-a",
        )
        self.stream_b = Stream.objects.create(
            name="Relay API Stream B",
            url="http://example.com/relay-api-b.ts",
            m3u_account=self.account,
            stream_profile=self.stream_profile_obj,
            stream_hash="pr6-relay-api-hash-b",
        )
        self.channel = Channel.objects.create(
            channel_number=9201,
            name="Relay API Channel",
            stream_profile=self.stream_profile_obj,
        )
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_a, order=0)
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_b, order=1)

    def _post(self, path, payload=None, *, signed=True):
        body = json.dumps(payload if payload is not None else {}).encode()
        headers = {}
        if signed:
            headers["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()
            headers["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = (
                build_internal_request_header("POST", path, body)
            )
        return self.client.post(path, data=body, content_type="application/json", **headers)

    def next_source_path(self, identifier):
        return f"/api/relay/channels/{identifier}/next-source"

    def release_path(self, identifier):
        return f"/api/relay/channels/{identifier}/release"


class GateTests(RelayApiTestCase):
    def test_every_route_refuses_a_request_with_no_internal_headers(self):
        for path in (
            self.next_source_path(str(self.channel.uuid)),
            self.release_path(str(self.channel.uuid)),
            "/api/relay/events",
        ):
            with self.subTest(path=path):
                response = self._post(path, {}, signed=False)
                self.assertEqual(response.status_code, 403)

    def test_every_route_refuses_an_authenticated_admin_without_the_headers(self):
        admin = User.objects.create_user(
            username="pr6-relay-api-admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.client.force_login(admin)
        for path in (
            self.next_source_path(str(self.channel.uuid)),
            self.release_path(str(self.channel.uuid)),
            "/api/relay/events",
        ):
            with self.subTest(path=path):
                response = self._post(path, {}, signed=False)
                self.assertEqual(response.status_code, 403)


class NextSourceRouteTests(RelayApiTestCase):
    def test_next_source_returns_the_contract_fields(self):
        path = self.next_source_path(str(self.channel.uuid))
        response = self._post(path, {})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        source = body["source"]
        self.assertEqual(source["stream_id"], self.stream_a.id)
        self.assertIn("url", source)
        self.assertIn("user_agent", source)
        self.assertEqual(source["m3u_profile_id"], self.m3u_profile.id)
        self.assertTrue(source["transcode"])
        self.assertTrue(source["slot_reserved"])
        self.assertEqual(
            source["stream_profile"],
            {
                "id": self.stream_profile_obj.id,
                "command": "ffmpeg",
                "args": "-i {streamUrl}",
            },
        )

    def test_next_source_reserves_a_slot_exactly_once_per_call(self):
        path = self.next_source_path(str(self.channel.uuid))
        key = f"profile_connections:{self.m3u_profile.id}"

        self.assertIsNone(self.redis.get(key))

        first = self._post(path, {})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["source"]["slot_reserved"])
        self.assertEqual(int(self.redis.get(key)), 1)

        second = self._post(path, {})
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["source"]["slot_reserved"])
        self.assertEqual(int(self.redis.get(key)), 1)

    def test_next_source_answers_200_with_a_null_source_when_nothing_is_left(self):
        path = self.next_source_path(str(self.channel.uuid))
        response = self._post(
            path,
            {
                "exclude_stream_ids": [self.stream_a.id, self.stream_b.id],
                "reason": "failover",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["source"])
        self.assertTrue(body["error"])

    def test_next_source_404s_an_unknown_identifier(self):
        path = self.next_source_path("not-a-channel-or-stream")
        response = self._post(path, {})
        self.assertEqual(response.status_code, 404)

    def test_current_stream_id_is_threaded_into_the_failover_traversal(self):
        # Fix round: NextSourceRequestSerializer's current_stream_id must
        # reach apps.proxy.next_source.get_alternate_streams(), which
        # rotates the failover traversal to start right after it
        # (order_alternates_from_current) -- the property
        # input/manager.py's pre-move _try_next_stream relies on today.
        path = self.next_source_path(str(self.channel.uuid))
        with patch(
            "apps.proxy.next_source.get_alternate_streams",
            return_value=[],
        ) as mock_get_alternates:
            response = self._post(
                path,
                {
                    "exclude_stream_ids": [999999],
                    "current_stream_id": self.stream_a.id,
                    "reason": "failover",
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_get_alternates.assert_called_once_with(
            str(self.channel.uuid), current_stream_id=self.stream_a.id
        )

    def test_next_source_returns_the_four_names_and_proxy_settings(self):
        """PIN. Phase 2 PR 2b-1: the wire, not just the resolver."""
        from core.models import CoreSettings

        response = self._post(self.next_source_path(str(self.channel.uuid)), {})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        source = body["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)
        self.assertIn("ffmpeg_stream_profile", source)
        self.assertEqual(
            body["proxy_settings"]["buffering_timeout"],
            CoreSettings.get_proxy_settings()["buffering_timeout"],
        )

    def test_next_source_resolves_a_stream_hash_identifier_over_http(self):
        """PIN for parity-matrix row 16's Django half.

        The single-stream admin preview (/proxy/ts/stream/<stream_hash>) has
        no Channel, and the relay sends whatever identifier arrived in the
        URL. next_source.get_stream_object already falls back from
        Channel.uuid to Stream.stream_hash -- this pins that the ROUTE does
        too, which nothing covered before: the existing coverage
        (test_next_source_resolution.py::
        test_a_stream_hash_identifier_resolves_the_stream_surface) calls
        resolve_source directly and would still pass if the view rejected
        the identifier shape.
        """
        response = self._post(self.next_source_path(self.stream_a.stream_hash), {})
        self.assertEqual(response.status_code, 200)
        source = response.json()["source"]
        self.assertEqual(source["stream_id"], self.stream_a.id)
        self.assertEqual(source["channel_name"], self.stream_a.name)


class ReleaseRouteTests(RelayApiTestCase):
    def test_release_gives_the_slot_back(self):
        next_path = self.next_source_path(str(self.channel.uuid))
        reserved = self._post(next_path, {})
        self.assertEqual(reserved.status_code, 200)

        profile_key = f"profile_connections:{self.m3u_profile.id}"
        channel_stream_key = f"channel_stream:{self.channel.id}"
        self.assertEqual(int(self.redis.get(profile_key)), 1)
        self.assertIsNotNone(self.redis.get(channel_stream_key))

        release_response = self._post(self.release_path(str(self.channel.uuid)), {})

        self.assertEqual(release_response.status_code, 200)
        self.assertTrue(release_response.json()["released"])
        self.assertEqual(int(self.redis.get(profile_key) or 0), 0)
        self.assertIsNone(self.redis.get(channel_stream_key))

    def test_release_frees_metadata_ids_when_identifier_resolves_to_neither_row(self):
        """Ruling 8: a channel deleted mid-playback resolves to neither a
        Channel nor a Stream row. release_view (api_views.py) performs no
        identifier resolution -- <str:identifier> matches anything -- so
        this is a pure pass-through to next_source.release_source()'s
        metadata-ids fallback, exercised here through the HTTP seam rather
        than by calling release_source() directly."""
        channel_stream_key = f"channel_stream:{self.channel.id}"
        stream_profile_key = f"stream_profile:{self.stream_a.id}"
        self.redis.set(channel_stream_key, self.stream_a.id)
        self.redis.set(stream_profile_key, self.m3u_profile.id)

        response = self._post(
            self.release_path("this-identifier-matches-nothing"),
            {
                "stream_id": self.stream_a.id,
                "m3u_profile_id": self.m3u_profile.id,
                "channel_pk": self.channel.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["released"])
        self.assertIsNone(self.redis.get(channel_stream_key))
        self.assertIsNone(self.redis.get(stream_profile_key))


class EventsRouteTests(RelayApiTestCase):
    def test_events_turns_a_batch_into_rows(self):
        response = self._post(
            "/api/relay/events",
            {
                "events": [
                    {
                        "type": "channel_start",
                        "channel_id": str(self.channel.uuid),
                        "details": {},
                    },
                    {
                        "type": "channel_failover",
                        "channel_id": str(self.channel.uuid),
                        "details": {},
                    },
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"accepted": 2, "rejected": 0})
        self.assertEqual(SystemEvent.objects.count(), 2)

    def test_a_blank_channel_id_writes_a_row_with_a_null_channel_id(self):
        # RelayEventSerializer.channel_id needs allow_blank=True (a
        # channel-less vod_start, built by hand rather than through
        # control_plane.emit_event, may legitimately send ""); this
        # exercises core.relay_events._clean() end to end, through the
        # view, not just at the writer layer.
        response = self._post(
            "/api/relay/events",
            {
                "events": [
                    {
                        "type": "vod_start",
                        "channel_id": "",
                        "details": {"content_name": "Movie Title"},
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"accepted": 1, "rejected": 0})
        row = SystemEvent.objects.get()
        self.assertIsNone(row.channel_id)


class SchemaTests(RelayApiTestCase):
    def test_the_three_routes_appear_in_the_openapi_schema(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        for path in (
            "/api/relay/channels/{identifier}/next-source",
            "/api/relay/channels/{identifier}/release",
            "/api/relay/events",
        ):
            self.assertIn(path, schema["paths"])
