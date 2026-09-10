"""What the two status endpoints put on the wire (parity-matrix row 14).

Two builders read one Redis hash and disagree in three ways. 2c has to
reproduce all three, so all three are asserted here against the JSON a
client of /proxy/relay/... actually receives -- not against the builders'
Python dicts, where a serializer could still change the answer.

No tune: the subject is what the builders and serializers do with a metadata
hash, so the test writes one.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.relay import RelayHarnessTestCase


def _signed(method, path, body=b""):
    """The two headers IsInternalRelay requires, minted the production way.

    Deliberately a module-local copy rather than a harness addition: 2a-3,
    2a-4 and 2a-6 branch off the same commit and the harness package is the
    one file their diffs can collide in.

    `path` carries the query string, because internal_auth.py:174-186 signs
    request.get_full_path() and not request.path.
    """
    return {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header(method, path, body),
    }


class StatusWireShapeTests(RelayHarnessTestCase):
    def setUp(self):
        super().setUp()
        self.identifier = str(uuid_module.uuid4())
        self.redis = ProxyServer.get_instance().redis_client
        self.assertIsNotNone(self.redis, "the harness needs a real Redis client")
        self.addCleanup(self.redis.delete, RedisKeys.channel_metadata(self.identifier))

    def _seed(self, **fields):
        self.redis.hset(RedisKeys.channel_metadata(self.identifier), mapping=fields)

    def _detail(self):
        path = f"/proxy/relay/channels/{self.identifier}"
        response = requests.get(
            self.live_server_url + path, headers=_signed("GET", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def _list_row(self):
        path = "/proxy/relay/channels"
        response = requests.get(
            self.live_server_url + path, headers=_signed("GET", path), timeout=10
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        rows = [
            row
            for row in response.json()["channels"]
            if row["channel_id"] == self.identifier
        ]
        self.assertEqual(len(rows), 1, "exactly one row for the seeded channel")
        return rows[0]

    def test_owner_is_the_string_unknown_on_detail_and_null_on_list(self):
        # The asymmetry itself, and the reason a test that checks one
        # endpoint proves nothing about the other. channel_status.py:45
        # supplies 'unknown' as get()'s default; :460 supplies none.
        self._seed(**{ChannelMetadataField.STATE: ChannelState.ACTIVE})

        self.assertEqual(self._detail()["owner"], "unknown")

        row = self._list_row()
        self.assertIn("owner", row)
        self.assertIsNone(row["owner"])

    def test_source_fps_is_a_string_on_detail_and_a_float_on_list(self):
        # channel_status.py:339 passes the raw Redis string through;
        # :595 coerces. relay_serializers.py types the field to match
        # (:129 CharField, :59 FloatField). Carried, not fixed (spec D5).
        self._seed(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.SOURCE_FPS: "29.97",
        })

        self.assertEqual(self._detail()["source_fps"], "29.97")
        self.assertEqual(self._list_row()["source_fps"], 29.97)

    def test_ffmpeg_speed_is_a_float_on_both_endpoints(self):
        # The half of the old string/float split that Phase 1 PR 7 closed
        # (channel_status.py:376 and :599 both float()). Asserted so the
        # Go relay is held to the fixed behaviour, not the historical one.
        self._seed(**{
            ChannelMetadataField.STATE: ChannelState.ACTIVE,
            ChannelMetadataField.FFMPEG_SPEED: "1.02",
        })

        self.assertEqual(self._detail()["ffmpeg_speed"], 1.02)
        self.assertEqual(self._list_row()["ffmpeg_speed"], 1.02)

    def test_state_is_null_rather_than_the_string_unknown_when_never_recorded(self):
        # A hash with no state field at all: both builders read it with a
        # bare get(), so the wire carries null. CLAUDE.md records this as
        # the field that used to disagree and no longer does.
        self._seed(**{ChannelMetadataField.CHANNEL_NAME: "seeded"})

        self.assertIsNone(self._detail()["state"])
        self.assertIsNone(self._list_row()["state"])

    def test_optional_fields_are_absent_entirely_rather_than_null(self):
        # relay_serializers.py:8-16: every optional field is required=False
        # with no default, so DRF's SkipField keeps an absence an absence.
        # A `default=` anywhere in those serializers would turn each of
        # these into a null and silently change /proxy/ts/status.
        self._seed(**{ChannelMetadataField.STATE: ChannelState.ACTIVE})

        detail = self._detail()
        for field in ("total_bytes", "avg_bitrate_kbps", "stream_id", "stream_name"):
            self.assertNotIn(field, detail, f"{field} must be absent, not null")

        row = self._list_row()
        for field in ("total_bytes", "avg_bitrate_kbps", "stream_id", "stream_name"):
            self.assertNotIn(field, row, f"{field} must be absent, not null")
