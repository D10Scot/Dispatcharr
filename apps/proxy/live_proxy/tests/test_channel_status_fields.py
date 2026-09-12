"""channel_status.py's seeded-hash decision branches (Phase 2 PR 2b-4, kinds 2+7).

Almost all one- and two-line branches over a metadata hash the test writes
itself. `_execute_redis_command`'s two-arm wrapper (this module's copy) is
Task 7's territory (kind 6), not this file's -- covering it here would
double-count it against Task 7's estimate.
"""
import time
from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from apps.proxy.live_proxy.channel_status import ChannelStatus, build_live_channel_stats_data


class ChannelStatusFixture(SimpleTestCase):
    def _info(self, metadata, *, buffer_index="1", client_metadata=None, client_ids=()):
        """Drive get_detailed_channel_info over a hand-written metadata hash.

        ProxyServer is patched because it is the SOURCE of the hash, not the
        subject: every branch this file tests -- the byte ladder, the
        bitrate formatting, the int-parse arms -- runs unpatched on the
        dict below.
        """
        with patch("apps.proxy.live_proxy.channel_status.ProxyServer") as proxy_cls, \
             patch("apps.proxy.live_proxy.channel_status.close_old_connections"):
            proxy_server = MagicMock()
            proxy_server.redis_client = MagicMock()
            proxy_server.redis_client.hgetall.side_effect = (
                lambda key: (client_metadata or {}).get(key, {})
                if client_metadata is not None and "clients:" in key
                else metadata
            )
            proxy_server.redis_client.get.return_value = buffer_index
            proxy_server.redis_client.smembers.return_value = set(client_ids)
            proxy_server.redis_client.exists.return_value = False
            proxy_cls.get_instance.return_value = proxy_server
            return ChannelStatus.get_detailed_channel_info("chan-uuid")

    def _basic_info(self, metadata, *, client_ids=()):
        """Drive get_basic_channel_info over a hand-written metadata hash."""
        with patch("apps.proxy.live_proxy.channel_status.ProxyServer") as proxy_cls:
            proxy_server = MagicMock()
            proxy_server.redis_client = MagicMock()
            proxy_server.redis_client.hgetall.return_value = metadata
            proxy_server.redis_client.smembers.return_value = set(client_ids)
            proxy_server.stream_managers = {}
            proxy_cls.get_instance.return_value = proxy_server
            return ChannelStatus.get_basic_channel_info("chan-uuid"), proxy_server


class AbsentMetadataAndDurationGuardTests(ChannelStatusFixture):
    def test_no_metadata_hash_returns_none(self):
        self.assertIsNone(self._info({}))

    def test_calculate_bitrate_non_positive_duration_is_zero(self):
        self.assertEqual(ChannelStatus._calculate_bitrate(1000, 0), 0)
        self.assertEqual(ChannelStatus._calculate_bitrate(1000, -1), 0)

    def test_owner_fallback_is_the_literal_string_unknown_not_none(self):
        # CLAUDE.md names this a carried, deliberate defect: truthiness
        # checks pass when nobody owns the channel. Pinned as behaviour so
        # 2c reproduces it rather than "fixing" it as a side effect.
        info = self._info({"state": "active"})
        self.assertEqual(info["owner"], "unknown")


class TotalDataLadderAndBitrateTests(ChannelStatusFixture):
    def test_the_total_data_ladder_formats_each_rung(self):
        for total_bytes, expected in [
            (512, "512 B"),
            (1536, "1.50 KB"),
            (1572864, "1.50 MB"),
            (1610612736, "1.50 GB"),
        ]:
            with self.subTest(total_bytes=total_bytes):
                info = self._info({"state": "active", "total_bytes": str(total_bytes)})
                self.assertEqual(info["total_data"], expected)
                self.assertEqual(info["total_bytes"], total_bytes)

    def test_avg_bitrate_formats_mbps_above_1000_kbps(self):
        # uptime = time.time() - init_time; patch time.time to a fixed value
        # so the expected string is a literal, not a recomputation.
        with patch("apps.proxy.live_proxy.channel_status.time.time", return_value=2000.0):
            info = self._info({
                "state": "active",
                "init_time": "1000.0",
                # 200,000,000 bytes over 1000s = 1,600,000 bits/s = 1600 Kbps
                "total_bytes": str(200_000_000),
            })
        self.assertEqual(info["avg_bitrate_kbps"], 1600.0)
        self.assertEqual(info["avg_bitrate"], "1.60 Mbps")

    def test_avg_bitrate_formats_kbps_at_or_below_1000(self):
        with patch("apps.proxy.live_proxy.channel_status.time.time", return_value=2000.0):
            info = self._info({
                "state": "active",
                "init_time": "1000.0",
                # 50,000,000 bytes over 1000s = 400,000 bits/s = 400 Kbps
                "total_bytes": str(50_000_000),
            })
        self.assertEqual(info["avg_bitrate_kbps"], 400.0)
        self.assertEqual(info["avg_bitrate"], "400.00 Kbps")

    def test_total_bytes_present_but_no_init_time_omits_avg_bitrate_kbps(self):
        info = self._info({"state": "active", "total_bytes": "1000"})
        # CLAUDE.md's contract: can be absent entirely (not null).
        self.assertNotIn("avg_bitrate_kbps", info)
        self.assertNotIn("avg_bitrate", info)


class DetailedInfoOrmFallbackTests(ChannelStatusFixture):
    def test_stream_name_orm_fallback_failure_is_logged_and_omitted(self):
        with patch(
            "apps.channels.models.Stream.objects"
        ) as mock_manager, self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            mock_manager.filter.side_effect = DatabaseError("db down")
            info = self._info({"state": "active", "stream_id": "7"})
        self.assertNotIn("stream_name", info)
        self.assertIn("Failed to get stream name for ID 7", logs.output[0])

    def test_m3u_profile_name_orm_fallback_failure_is_logged_and_omitted(self):
        with patch(
            "apps.m3u.models.M3UAccountProfile.objects"
        ) as mock_manager, self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            mock_manager.filter.side_effect = DatabaseError("db down")
            info = self._info({"state": "active", "m3u_profile": "3"})
        self.assertNotIn("m3u_profile_name", info)
        self.assertIn("Failed to get M3U profile name for ID 3", logs.output[0])

    def test_a_non_numeric_stream_id_warns_and_omits_the_field(self):
        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            info = self._info({"state": "active", "stream_id": "not-an-int"})
        self.assertNotIn("stream_id", info)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("Invalid stream_id format in Redis", logs.output[0])
        self.assertIn("not-an-int", logs.output[0])

    def test_a_non_numeric_m3u_profile_id_warns_and_omits_the_name(self):
        """channel_status.py's except ValueError around int(m3u_profile).

        The arm's own product is the warning naming the bad value and the
        ABSENCE of m3u_profile_name -- both asserted, because "did not
        raise" would hold with the whole try/except deleted.
        """
        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            info = self._info({"state": "active", "m3u_profile": "not-an-int"})
        self.assertNotIn("m3u_profile_name", info)
        self.assertEqual(len(logs.records), 1)
        # The VALUE, not just the string: "Invalid m3u_profile_id format in
        # Redis" is emitted from this arm AND from get_basic_channel_info's
        # own copy, in a different function. Pinning the message alone gives
        # two tests that pass with the arms swapped; the rejected value
        # reaches this message via m3u_profile_id_bytes, so asserting it is
        # what ties this assertion to THIS arm.
        self.assertIn("Invalid m3u_profile_id format in Redis", logs.output[0])
        self.assertIn("not-an-int", logs.output[0])

    def test_source_bitrate_is_passed_through_when_present(self):
        info = self._info({"state": "active", "source_bitrate": "5000"})
        self.assertEqual(info["source_bitrate"], "5000")

    def test_ffmpeg_bitrate_is_passed_through_when_present(self):
        info = self._info({"state": "active", "ffmpeg_bitrate": "3500"})
        self.assertEqual(info["ffmpeg_bitrate"], "3500")


class DetailedInfoClientRowTests(ChannelStatusFixture):
    def test_a_ghost_client_is_skipped_from_the_list(self):
        info = self._info(
            {"state": "active"}, client_ids=["ghost-1"], client_metadata={},
        )
        self.assertEqual(info["clients"], [])

    def test_output_profile_id_parsing_four_cases(self):
        for raw, expected in [("5", 5), ("None", None), ("0", None), ("", None)]:
            with self.subTest(raw=raw):
                client_key = "live:channel:chan-uuid:clients:c1"
                info = self._info(
                    {"state": "active"},
                    client_ids=["c1"],
                    client_metadata={
                        client_key: {"output_profile_id": raw, "user_agent": "ua"}
                    },
                )
                self.assertEqual(info["clients"][0]["output_profile_id"], expected)

    def test_transfer_rate_kbps_legacy_fallback_and_precedence(self):
        client_key = "live:channel:chan-uuid:clients:c1"
        # avg_rate_KBps only
        info = self._info(
            {"state": "active"}, client_ids=["c1"],
            client_metadata={client_key: {"avg_rate_KBps": "12.5"}},
        )
        self.assertEqual(info["clients"][0]["avg_rate_KBps"], 12.5)

        # transfer_rate_KBps only (legacy field)
        info = self._info(
            {"state": "active"}, client_ids=["c1"],
            client_metadata={client_key: {"transfer_rate_KBps": "7.0"}},
        )
        self.assertEqual(info["clients"][0]["avg_rate_KBps"], 7.0)

        # Both present -- avg_rate_KBps wins (the only case that pins the elif).
        info = self._info(
            {"state": "active"}, client_ids=["c1"],
            client_metadata={
                client_key: {"avg_rate_KBps": "12.5", "transfer_rate_KBps": "7.0"}
            },
        )
        self.assertEqual(info["clients"][0]["avg_rate_KBps"], 12.5)


class BasicChannelInfoTests(ChannelStatusFixture):
    def test_no_metadata_hash_returns_none(self):
        info, _ = self._basic_info({})
        self.assertIsNone(info)

    def test_logo_id_and_m3u_profile_id_unparseable_are_silently_skipped(self):
        info, _ = self._basic_info({
            "state": "active", "logo_id": "not-an-int", "m3u_profile": "also-bad",
        })
        self.assertNotIn("logo_id", info)
        self.assertNotIn("m3u_profile_id", info)

    def test_a_non_numeric_stream_id_warns_and_omits_the_field(self):
        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            info, _ = self._basic_info({"state": "active", "stream_id": "not-an-int"})
        self.assertNotIn("stream_id", info)
        self.assertIn("Invalid stream_id format in Redis", logs.output[0])
        self.assertIn("not-an-int", logs.output[0])

    def test_a_non_numeric_m3u_profile_id_warns_and_omits_the_field(self):
        with self.assertLogs("live_proxy.channel_status", level="WARNING") as logs:
            info, _ = self._basic_info({"state": "active", "m3u_profile": "not-an-int"})
        self.assertNotIn("m3u_profile_id", info)
        # Same message-plus-value pinning as the detailed-info arm above:
        # this string is also emitted from get_detailed_channel_info's own
        # copy of this check.
        self.assertIn("Invalid m3u_profile_id format in Redis", logs.output[0])
        self.assertIn("not-an-int", logs.output[0])

    def test_an_unexpected_exception_is_logged_and_answered_as_none(self):
        with patch(
            "apps.proxy.live_proxy.channel_status.ClientManager.remove_ghost_clients",
            side_effect=RuntimeError("boom"),
        ), self.assertLogs("live_proxy.channel_status", level="ERROR") as logs:
            info, _ = self._basic_info(
                {"state": "active"}, client_ids=["c1"],
            )
        self.assertIsNone(info)
        self.assertIn("Error getting channel info: boom", logs.output[0])


class BuildLiveChannelStatsDataTests(SimpleTestCase):
    def test_a_key_not_matching_the_channel_id_pattern_is_skipped(self):
        redis_client = MagicMock()
        redis_client.scan.return_value = (0, ["not-a-channel-key"])
        result = build_live_channel_stats_data(redis_client)
        self.assertEqual(result, {"channels": [], "count": 0})
