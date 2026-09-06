"""Channel delete must not auto-stop proxy sessions; stop runs outside delete TX."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.channels.models import Channel, ChannelGroup


class CleanRedisKeysUsesStandardCloseTests(SimpleTestCase):
    @patch("apps.proxy.live_proxy.server.close_old_connections")
    @patch("apps.proxy.control_plane.release_source", return_value=False)
    def test_clean_redis_keys_uses_close_old_connections(
        self, _release_source, mock_close
    ):
        from apps.proxy.live_proxy.server import ProxyServer

        with patch(
            "apps.proxy.live_proxy.server.RedisClient.get_client",
            return_value=MagicMock(),
        ):
            server = ProxyServer()
        server.redis_client = MagicMock()
        server.redis_client.scan.return_value = (0, [])
        mock_close.reset_mock()

        server._clean_redis_keys("channel-uuid")

        mock_close.assert_called()
        self.assertGreaterEqual(mock_close.call_count, 1)


class UpdateStreamStatsPostsAnEventTests(SimpleTestCase):
    @patch("apps.proxy.control_plane.emit_event")
    def test_update_stream_stats_posts_rather_than_writes(self, mock_emit):
        from apps.proxy.live_proxy.services.channel_service import ChannelService

        self.assertTrue(
            ChannelService._update_stream_stats_in_db(123, ffmpeg_output_bitrate=1.0)
        )
        mock_emit.assert_called_once_with(
            "stream_stats", stream_id=123, ffmpeg_output_bitrate=1.0
        )


class ChannelDeleteDoesNotAutoStopTests(TestCase):
    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Delete Proxy Group")
        self.channel = Channel.objects.create(
            channel_number=870.0,
            name="Playing Channel",
            channel_group=self.group,
        )

    @patch(
        "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channel"
    )
    def test_model_delete_does_not_stop_proxy(self, mock_stop):
        channel_id = self.channel.id

        self.channel.delete()

        mock_stop.assert_not_called()
        self.assertFalse(Channel.objects.filter(pk=channel_id).exists())
