"""The golden fixture for the Go relay's GET /proxy/relay/channels.

Phase 2 PR 2c-3. This file renders a payload through Django's own
RelayChannelListSerializer and pins the result to
relay/httpapi/testdata/channels_clients_all.json, which a Go test reads back.
That is the whole point: the Go encoder is compared against the OTHER
implementation, not against a Go struct literal the same PR also wrote.

WHAT THIS PINS AND WHAT IT DOES NOT. It pins the SERIALIZER -- which keys
survive, which render as null, which vanish. It does NOT drive
ChannelStatus.get_basic_channel_info, so the mapping from "the source dict set
this key inside an if" to "this key is optional" is 2c-3's reading of
apps/proxy/live_proxy/channel_status.py:469-587, not a measurement of Python's
execution. Driving the real builder would need a Redis with a channel in it,
which is a much heavier fixture for one more link in the chain; the
completeness assertion below is what stops the reading from silently narrowing
instead.

Regenerate the golden with:

    DISPATCHARR_WRITE_GOLDEN=1 python manage.py test \\
        apps.proxy.tests.test_relay_list_payload_golden
"""

import json
import os
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.relay_serializers import (
    RelayChannelListSerializer,
    RelayChannelSerializer,
)

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "relay"
    / "httpapi"
    / "testdata"
    / "channels_clients_all.json"
)

# Every RelayChannelSerializer field the Go relay does not produce yet, and
# why. A field in neither this mapping nor the fully-populated fixture channel
# fails test_the_fixture_covers_every_serializer_field, which is what stops
# the golden from silently narrowing as the endpoint grows. 2c-3 excused nine;
# 2c-4's transcode source produces seven of them (the input format included --
# it is log_parsers.py's parse_input_format, not 2c-5's).
NOT_SERVED_YET = {
    "logo_id": (
        "ChannelMetadataField.LOGO_ID is written only into the TIMESHIFT key "
        "family (apps/timeshift/views.py:2984, timeshift:channel:<id>:metadata), "
        "never into the live:channel:<uuid>:metadata hash channel_status.py:486 "
        "reads, so the live list endpoint never emits it in Python either"
    ),
    "healthy": "needs StreamManager.healthy, which arrives in 2c-5",
}


def fixture():
    """Two channels: one with every conditional field and two clients, one with
    none and no clients. Every present/absent/null case this endpoint can
    produce is in here."""
    return {
        "count": 2,
        "channels": [
            {
                "channel_id": "11111111-1111-4111-8111-111111111111",
                "state": "active",
                "url": "http://provider.invalid/live/sub/pw/41.ts",
                "stream_profile": "1",
                "owner": None,
                "buffer_index": 120,
                "client_count": 2,
                "uptime": 30.0,
                "started_at": 1789000000.5,
                "channel_name": "BBC One HD",
                "m3u_profile_id": 3,
                "stream_id": 41,
                "stream_name": "BBC One HD (UK)",
                "total_bytes": 9999888,
                "avg_bitrate_kbps": 2665.3034666666666,
                "avg_bitrate": "2.67 Mbps",
                # The seven ffmpeg-derived fields, Phase 2 PR 2c-4: present only
                # when a transcode process reported them (channel_status.py:
                # 605-627). source_fps is a FLOAT on this endpoint and a string
                # on the detail one (parity-matrix row 14).
                "video_codec": "h264",
                "resolution": "1920x1080",
                "source_fps": 25.0,
                "ffmpeg_speed": 1.02,
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "stream_type": "mpegts",
                "clients": [
                    {
                        "client_id": "client_1789000000000_1234",
                        "user_agent": "VLC/3.0.20",
                        "output_format": "mpegts",
                        "output_profile_id": 7,
                        "ip_address": "198.51.100.4",
                        "connected_at": 1789000001.25,
                        "user_id": "7",
                    },
                    {
                        # Nothing optional. user_agent and output_profile_id
                        # are assigned on every path in channel_status.py and
                        # are therefore present-as-null, not absent.
                        "client_id": "client_1789000000000_5678",
                        "user_agent": None,
                        "output_format": "mpegts",
                        "output_profile_id": None,
                    },
                ],
            },
            {
                "channel_id": "22222222-2222-4222-8222-222222222222",
                "state": "stopped",
                "url": "",
                "stream_profile": "0",
                "owner": None,
                "buffer_index": 0,
                "client_count": 0,
                "uptime": 0.0,
                "started_at": 1789000100.0,
                "clients": [],
            },
        ],
    }


def rendered():
    return JSONRenderer().render(RelayChannelListSerializer(fixture()).data)


class RelayListPayloadGoldenTests(SimpleTestCase):
    def test_the_golden_file_is_what_the_serializer_renders(self):
        payload = rendered()
        if os.environ.get("DISPATCHARR_WRITE_GOLDEN") == "1":
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_bytes(payload)
            self.skipTest(f"rewrote {GOLDEN}")

        self.assertTrue(
            GOLDEN.exists(),
            f"{GOLDEN} is missing; regenerate it with DISPATCHARR_WRITE_GOLDEN=1",
        )
        # Parsed, not byte-compared, for the same reason the Go side does:
        # nothing downstream compares bytes, and a whitespace difference
        # between two JSON writers is not a contract change.
        self.assertEqual(
            json.loads(GOLDEN.read_bytes()),
            json.loads(payload),
            "relay/httpapi/testdata/channels_clients_all.json has drifted from "
            "what RelayChannelListSerializer renders; regenerate it with "
            "DISPATCHARR_WRITE_GOLDEN=1 and read the diff before committing",
        )

    def test_the_fixture_covers_every_serializer_field(self):
        """Every declared field is exercised or explicitly excused.

        Without this, a hand-written fixture that quietly omitted a field
        would pin a payload narrower than the contract, and the Go side would
        agree with it.
        """
        declared = set(RelayChannelSerializer().fields)
        populated = set(fixture()["channels"][0])
        excused = set(NOT_SERVED_YET)

        missing = declared - populated - excused
        self.assertEqual(
            missing,
            set(),
            "these RelayChannelSerializer fields are neither in the fixture nor "
            f"in NOT_SERVED_YET with a reason: {sorted(missing)}",
        )
        stale = excused - declared
        self.assertEqual(
            stale,
            set(),
            f"NOT_SERVED_YET names fields the serializer does not declare: {sorted(stale)}",
        )

    def test_an_unset_optional_field_vanishes_rather_than_rendering_null(self):
        """The DRF behaviour the whole golden rests on.

        required=False with NO default= makes Field.get_attribute raise
        SkipField for a missing key, so the key leaves the JSON entirely. A
        default= on any of them would turn every absence into a null and change
        /proxy/ts/status and /proxy/stats/ as well.
        """
        minimal = json.loads(rendered())["channels"][1]
        for key in ("channel_name", "stream_id", "total_bytes", "avg_bitrate"):
            self.assertNotIn(key, minimal, f"{key} rendered for a channel that has none")
        for key in ("channel_id", "state", "url", "owner", "clients"):
            self.assertIn(key, minimal, f"{key} must be present on every channel")
        self.assertIsNone(minimal["owner"])
        self.assertEqual(minimal["clients"], [])
