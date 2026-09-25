"""The golden fixture for the Go relay's GET /proxy/relay/channels/<id>.

Phase 2 PR 2c-8, and the sibling of test_relay_list_payload_golden.py. This
file renders a payload through Django's own RelayChannelDetailSerializer and
pins the result to relay/httpapi/testdata/channel_detail.json, which a Go test
reads back. The Go encoder is compared against the OTHER implementation, not
against a Go struct literal the same PR also wrote.

WHAT THIS PINS AND WHAT IT DOES NOT, unchanged from the list golden's own
statement of it: it pins the SERIALIZER -- which keys survive, which render as
null, which vanish. It does not drive
ChannelStatus.get_detailed_channel_info, so the mapping from "the source dict
set this key inside an if" to "this key is optional" is 2c-8's reading of
apps/proxy/live_proxy/channel_status.py:25-413, and the completeness assertion
below is what stops that reading from silently narrowing.

Regenerate the golden with:

    DISPATCHARR_WRITE_GOLDEN=1 python manage.py test \\
        apps.proxy.tests.test_relay_detail_payload_golden
"""

import json
import os
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.relay_serializers import (
    RelayChannelDetailSerializer,
    RelayDetailClientSerializer,
)

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "relay"
    / "httpapi"
    / "testdata"
    / "channel_detail.json"
)

# RelayChannelDetailSerializer fields the Go relay never emits, each with the
# reason. Kept as a mapping with a reason for the list golden's reason -- a
# field in neither this mapping nor the fully-populated fixture fails
# test_the_fixture_covers_every_serializer_field, which is what stops the
# golden from narrowing as the endpoint grows.
#
# EMPTY SINCE ISSUE #314. It held source_bitrate, which nothing in either
# relay ever wrote and which the serializer no longer declares, and
# ffmpeg_bitrate, which the Go relay now emits from the output bitrate its
# stderr reader parses. With it empty, a serializer that still declared
# source_bitrate fails the completeness test below -- the pin for its
# removal.
NEVER_WRITTEN = {}


def fixture():
    """One channel with every conditional field set and two clients: a TS
    client carrying the three byte counters the TS generator writes, and an
    fMP4 client carrying none of them, which is the per-format asymmetry
    output/fmp4/generator.py:288-295 creates by writing only last_active."""
    return {
        "channel_id": "11111111-1111-4111-8111-111111111111",
        "state": "active",
        "url": "http://provider.invalid/live/sub/pw/41.ts",
        "stream_profile": "1",
        "started_at": 1789000000.5,
        # The literal string, not null: channel_status.py:45's default, and
        # parity-matrix row 14's asymmetry with the list endpoint.
        "owner": "unknown",
        "buffer_index": 120,
        "channel_name": "BBC One HD",
        "stream_id": 41,
        "stream_name": "BBC One HD (UK)",
        "m3u_profile_id": 3,
        "m3u_profile_name": "Premium",
        "state_changed_at": 1789000005.0,
        "state_duration": 25.5,
        "uptime": 30.0,
        "total_bytes": 9999888,
        "total_data": "9.54 MB",
        "avg_bitrate_kbps": 2665.3034666666666,
        "avg_bitrate": "2.67 Mbps",
        "client_count": 2,
        "buffer_stats": {
            "chunks": 120,
            "diagnostics": {
                "first_chunk": {
                    "index": 116,
                    "size": 255868,
                    "ts_packets": 1361,
                    "aligned": True,
                    "first_byte": 71,
                }
            },
            "avg_chunk_size": 255868.0,
            "recent_chunk_sizes": [255868, 255868, 255868, 255868, 255868],
            "keys_found": [116, 117, 118, 119, 120],
            "keys_missing": [],
            "total_sample_bytes": 1279340,
            "estimated_ts_packets": 6805,
            "is_ts_aligned": True,
        },
        "local_manager": {
            "healthy": True,
            "connected": True,
            "last_data_time": 1789000029.5,
            "last_data_age": 0.5,
        },
        # The stream-info fields, raw strings exactly as the hash stores them
        # (str(round(x, n)) at services/channel_service.py:844-880).
        "video_codec": "h264",
        "resolution": "1920x1080",
        "width": "1920",
        "height": "1080",
        "video_bitrate": "4500.0",
        # A STRING here and a float on the list endpoint: row 14.
        "source_fps": "25.0",
        "pixel_format": "yuv420p",
        "audio_codec": "aac",
        "sample_rate": "48000",
        "audio_channels": "stereo",
        "audio_bitrate": "128.0",
        # A FLOAT on both endpoints (Phase 1 PR 7 unified it); row 14 again.
        "ffmpeg_speed": 1.02,
        "ffmpeg_fps": "25.0",
        "actual_fps": "24.5",
        # Issue #314: the output bitrate, str(round(kbps, 1)) as the other
        # detail-endpoint rates are.
        "ffmpeg_bitrate": "4200.0",
        "stream_type": "mpegts",
        "clients": [
            {
                "client_id": "client_1789000000000_1234",
                "user_agent": "VLC/3.0.20",
                # 'unknown' with one relay process and no election -- the
                # same default channel_status.py:181 applies when the client
                # hash carries no worker_id.
                "worker_id": "unknown",
                "ip_address": "198.51.100.4",
                "user_id": "7",
                "output_format": "mpegts",
                "output_profile_id": 7,
                "connected_at": 1789000001.25,
                "last_active": 1789000029.5,
                "last_active_ago": 0.5,
                "bytes_sent": 9999888,
                "avg_rate_KBps": 341.2,
                "current_rate_KBps": 348.9,
            },
            {
                # An fMP4 client: the three byte counters are ABSENT, because
                # output/fmp4/generator.py writes only last_active.
                "client_id": "client_1789000000000_5678",
                "user_agent": "unknown",
                "worker_id": "unknown",
                "ip_address": "198.51.100.9",
                "user_id": "0",
                "output_format": "fmp4",
                "output_profile_id": None,
                "connected_at": 1789000010.0,
                "last_active": 1789000029.0,
                "last_active_ago": 1.0,
            },
        ],
    }


def rendered():
    return JSONRenderer().render(RelayChannelDetailSerializer(fixture()).data)


class RelayDetailPayloadGoldenTests(SimpleTestCase):
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
        self.assertEqual(
            json.loads(GOLDEN.read_bytes()),
            json.loads(payload),
            "relay/httpapi/testdata/channel_detail.json has drifted from what "
            "RelayChannelDetailSerializer renders; regenerate it with "
            "DISPATCHARR_WRITE_GOLDEN=1 and read the diff before committing",
        )

    def test_the_fixture_covers_every_serializer_field(self):
        declared = set(RelayChannelDetailSerializer().fields)
        populated = set(fixture())
        excused = set(NEVER_WRITTEN)

        missing = declared - populated - excused
        self.assertEqual(
            missing,
            set(),
            "these RelayChannelDetailSerializer fields are neither in the "
            f"fixture nor in NEVER_WRITTEN with a reason: {sorted(missing)}",
        )
        stale = excused - declared
        self.assertEqual(
            stale,
            set(),
            f"NEVER_WRITTEN names fields the serializer does not declare: {sorted(stale)}",
        )

    def test_the_client_fixture_covers_every_detail_client_field(self):
        """The same completeness check one level down.

        The TS client carries every field; the fMP4 one is where the
        conditional half is exercised, so the union is what has to be
        complete and the TS row alone is what has to cover it.
        """
        declared = set(RelayDetailClientSerializer().fields)
        populated = set(fixture()["clients"][0])
        self.assertEqual(
            declared - populated,
            set(),
            "these RelayDetailClientSerializer fields are not in the fully "
            f"populated client row: {sorted(declared - populated)}",
        )

    def test_the_fmp4_client_row_omits_the_three_byte_counters(self):
        """The per-format asymmetry, asserted on the RENDERED payload.

        A test that only checked the TS row would pass with an fMP4 row that
        carried counters too -- which is the shape a Go relay gets by
        recording bytes for every client and letting the renderer decide.
        """
        client = json.loads(rendered())["clients"][1]
        for key in ("bytes_sent", "avg_rate_KBps", "current_rate_KBps"):
            self.assertNotIn(
                key,
                client,
                f"{key} rendered for an fMP4 client, whose generator never writes it",
            )
        # And the fields it DOES carry, so "everything vanished" cannot be
        # what makes this pass.
        for key in ("client_id", "worker_id", "connected_at", "last_active"):
            self.assertIn(key, client, f"{key} is missing from the fMP4 client row")

    def test_owner_is_the_string_unknown_here_and_null_on_the_list(self):
        """Parity-matrix row 14's first clause, across BOTH serializers.

        Asserted here as well as on the list golden because a test that
        checks the string against only one of the two endpoints proves
        nothing about the other -- the row's own Notes say so.
        """
        from apps.proxy.tests.test_relay_list_payload_golden import (
            fixture as list_fixture,
            rendered as list_rendered,
        )

        self.assertEqual(json.loads(rendered())["owner"], "unknown")
        self.assertIsNone(json.loads(list_rendered())["channels"][0]["owner"])
        self.assertIsNone(list_fixture()["channels"][0]["owner"])

    def test_source_fps_is_a_string_here_and_a_float_on_the_list(self):
        """Row 14's third clause, the one Phase 1 PR 7 did NOT unify."""
        from apps.proxy.tests.test_relay_list_payload_golden import (
            rendered as list_rendered,
        )

        self.assertIsInstance(json.loads(rendered())["source_fps"], str)
        self.assertIsInstance(
            json.loads(list_rendered())["channels"][0]["source_fps"], float
        )

    def test_ffmpeg_speed_is_a_float_on_both_endpoints(self):
        """Row 14's second clause, which PR 7 DID unify. Held unified."""
        from apps.proxy.tests.test_relay_list_payload_golden import (
            rendered as list_rendered,
        )

        self.assertIsInstance(json.loads(rendered())["ffmpeg_speed"], float)
        self.assertIsInstance(
            json.loads(list_rendered())["channels"][0]["ffmpeg_speed"], float
        )
