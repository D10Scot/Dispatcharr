"""PINs for Phase 2 PR 2b-1: the names arrive from Django and are stored,
so the relay never re-queries for them.

Spec: docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
§ Stage 2b, the services/channel_service.py:324,331,911 row.
"""

import json
from unittest.mock import patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.services.channel_service import ChannelService


class InitializeChannelStoresTheNamesTests(TestCase):
    def _redis(self):
        """A ProxyServer whose redis_client records every hset mapping."""
        from unittest.mock import MagicMock

        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.initialize_channel.return_value = True
        return proxy_server

    def _written(self, redis_client):
        """Every field any hset wrote, merged."""
        written = {}
        for call in redis_client.hset.call_args_list:
            mapping = call.kwargs.get("mapping")
            if mapping:
                written.update(mapping)
            elif len(call.args) == 3:
                written[call.args[1]] = call.args[2]
        return written

    def test_the_supplied_names_reach_the_metadata_hash(self):
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
            )
        written = self._written(proxy_server.redis_client)
        self.assertEqual(written[ChannelMetadataField.CHANNEL_NAME], "BBC One")
        self.assertEqual(written[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(written[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertEqual(
            json.loads(written[ChannelMetadataField.FFMPEG_STREAM_PROFILE]),
            {"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
        )

    def test_the_names_land_before_the_stream_manager_starts(self):
        """PIN. StreamManager's own threads read this hash; a field written
        only AFTER proxy_server.initialize_channel() returns is racing them.
        Asserts the hash carried every name by the time initialize_channel
        was called, not merely by the time the method returned."""
        proxy_server = self._redis()
        seen = {}

        def capture(*args, **kwargs):
            seen.update(self._written(proxy_server.redis_client))
            return True

        proxy_server.initialize_channel.side_effect = capture
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
            )
        self.assertEqual(seen[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(seen[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertIn(ChannelMetadataField.FFMPEG_STREAM_PROFILE, seen)

    def test_initialize_channel_runs_no_query_when_the_names_are_supplied(self):
        """PIN. This is the whole point of the PR: with names in hand, the
        relay's init path touches the ORM zero times."""
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            with self.assertNumQueries(0):
                ChannelService.initialize_channel(
                    "chan-uuid", "http://u/s.ts", "UA",
                    stream_id=7, m3u_profile_id=3,
                    channel_name="BBC One", stream_name="BBC One HD",
                    m3u_profile_name="Provider A default",
                    ffmpeg_stream_profile=None,
                )
