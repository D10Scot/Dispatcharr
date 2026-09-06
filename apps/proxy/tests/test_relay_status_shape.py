"""The status payload's two type fixes, three additions and one parameter.

CLAUDE.md section Observing a channel records that get_detailed_channel_info
and get_basic_channel_info disagree about ffmpeg_speed's type and state's
default. PR 7 puts both behind one DRF serializer, so they have to agree
first. The three added fields exist because the DVR's metadata read moves
onto this payload (ruling 5) and reads width, height and video_bitrate,
which the detailed builder never emitted.
"""

from unittest import mock

from django.test import SimpleTestCase

from apps.proxy.live_proxy import channel_status
from apps.proxy.live_proxy.channel_status import (
    ChannelStatus,
    build_live_channel_stats_data,
)


def _metadata(**overrides):
    data = {
        "url": "http://provider.example/live",
        "stream_profile": "3",
        "owner": "worker-1",
        "init_time": "1000.0",
        "total_bytes": "2048",
        "video_codec": "h264",
        "resolution": "1920x1080",
        "width": "1920",
        "height": "1080",
        "video_bitrate": "4200",
        "source_fps": "25.0",
        "audio_codec": "aac",
        "audio_channels": "2",
        "stream_type": "hls",
        "ffmpeg_speed": "1.02",
    }
    data.update(overrides)
    return data


class _FakeRedis:
    """Only the calls both info builders make."""

    def __init__(self, metadata, client_ids=(), client_hashes=None):
        self._metadata = metadata
        self._client_ids = set(client_ids)
        self._client_hashes = client_hashes or {}

    def hgetall(self, key):
        if key.endswith(":metadata"):
            return dict(self._metadata)
        return dict(self._client_hashes.get(key, {}))

    def get(self, key):
        return "7" if key.endswith(":index") else None

    def smembers(self, key):
        return set(self._client_ids)

    def scard(self, key):
        return len(self._client_ids)

    def srem(self, key, *members):
        return 0

    def exists(self, key):
        return 1

    def ttl(self, key):
        return 60

    def hmget(self, key, *fields):
        row = self._client_hashes.get(key, {})
        return [row.get(f) for f in fields]

    def scan(self, cursor, match=None, count=None):
        return 0, ["live:channel:abc:metadata"]


class DetailedInfoTypeTests(SimpleTestCase):
    def _detailed(self, **overrides):
        fake = _FakeRedis(_metadata(**overrides))
        server = mock.Mock(redis_client=fake, stream_managers={})
        with mock.patch.object(
            channel_status.ProxyServer, "get_instance", return_value=server
        ):
            return ChannelStatus.get_detailed_channel_info("abc")

    def test_ffmpeg_speed_is_a_float_not_the_raw_redis_string(self):
        self.assertEqual(self._detailed()["ffmpeg_speed"], 1.02)

    def test_an_unparseable_ffmpeg_speed_is_omitted_rather_than_a_500(self):
        self.assertNotIn("ffmpeg_speed", self._detailed(ffmpeg_speed="N/A"))

    def test_state_is_null_when_absent_never_the_string_unknown(self):
        self.assertIsNone(self._detailed()["state"])

    def test_state_is_reported_when_present(self):
        self.assertEqual(self._detailed(state="active")["state"], "active")

    def test_the_three_dvr_video_fields_are_present_as_raw_strings(self):
        info = self._detailed()
        self.assertEqual(info["width"], "1920")
        self.assertEqual(info["height"], "1080")
        self.assertEqual(info["video_bitrate"], "4200")

    def test_the_three_dvr_fields_are_absent_when_redis_has_none(self):
        fake = _FakeRedis(
            {k: v for k, v in _metadata().items()
             if k not in ("width", "height", "video_bitrate")}
        )
        server = mock.Mock(redis_client=fake, stream_managers={})
        with mock.patch.object(
            channel_status.ProxyServer, "get_instance", return_value=server
        ):
            info = ChannelStatus.get_detailed_channel_info("abc")
        for field in ("width", "height", "video_bitrate"):
            self.assertNotIn(field, info)


class ClientLimitTests(SimpleTestCase):
    def _fake(self):
        ids = [f"c{i}" for i in range(14)]
        hashes = {
            f"live:channel:abc:clients:{cid}": {
                "user_agent": "vlc",
                "ip_address": "10.0.0.1",
                "connected_at": "1000.0",
                "user_id": "5",
                "output_format": "mpegts",
                "output_profile_id": "",
            }
            for cid in ids
        }
        return _FakeRedis(_metadata(), client_ids=ids, client_hashes=hashes)

    def _basic(self, **kwargs):
        fake = self._fake()
        server = mock.Mock(redis_client=fake, stream_managers={})
        with mock.patch.object(
            channel_status.ProxyServer, "get_instance", return_value=server
        ), mock.patch.object(
            channel_status.ClientManager, "remove_ghost_clients", return_value=set()
        ):
            return ChannelStatus.get_basic_channel_info("abc", **kwargs)

    def test_the_default_keeps_the_stats_payload_capped_at_ten(self):
        self.assertEqual(len(self._basic()["clients"]), 10)

    def test_client_limit_none_returns_every_client(self):
        # get_user_active_connections counts a user's connections; a cap
        # would under-count and let a viewer past their stream limit.
        self.assertEqual(len(self._basic(client_limit=None)["clients"]), 14)

    def test_client_count_is_the_true_count_either_way(self):
        self.assertEqual(self._basic()["client_count"], 14)

    def test_build_live_channel_stats_data_passes_the_limit_through(self):
        fake = self._fake()
        server = mock.Mock(redis_client=fake, stream_managers={})
        with mock.patch.object(
            channel_status.ProxyServer, "get_instance", return_value=server
        ), mock.patch.object(
            channel_status.ClientManager, "remove_ghost_clients", return_value=set()
        ):
            capped = build_live_channel_stats_data(fake)
            full = build_live_channel_stats_data(fake, client_limit=None)
        self.assertEqual(len(capped["channels"][0]["clients"]), 10)
        self.assertEqual(len(full["channels"][0]["clients"]), 14)
