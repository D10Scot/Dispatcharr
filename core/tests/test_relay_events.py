"""core.relay_events.apply_event_batch — Phase 1 PR 6, Task 5.

The relay used to call log_system_event() at thirteen sites and
Stream.save() at one; both now arrive here as one batch posted to
POST /api/relay/events (Task 6). These tests exercise the writer directly,
without the view.
"""

from unittest.mock import patch

from django.test import TestCase, TransactionTestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount
from core.models import SystemEvent


class EventBatchWritesSystemEventRowsTests(TestCase):
    def test_each_event_becomes_a_system_event_row(self):
        from core.relay_events import apply_event_batch

        channel_id = "11111111-1111-1111-1111-111111111111"
        counts = apply_event_batch(
            [
                {
                    "type": "channel_start",
                    "channel_id": channel_id,
                    "channel_name": "CNN",
                    "details": {"stream_url": "http://example/1"},
                },
                {
                    "type": "channel_failover",
                    "channel_id": channel_id,
                    "channel_name": "CNN",
                    "details": {"reason": "dead_air"},
                },
            ]
        )

        self.assertEqual(counts, {"accepted": 2, "rejected": 0})
        self.assertEqual(SystemEvent.objects.count(), 2)

        start = SystemEvent.objects.get(event_type="channel_start")
        self.assertEqual(str(start.channel_id), channel_id)
        self.assertEqual(start.channel_name, "CNN")
        self.assertEqual(start.details, {"stream_url": "http://example/1"})

        failover = SystemEvent.objects.get(event_type="channel_failover")
        self.assertEqual(str(failover.channel_id), channel_id)
        self.assertEqual(failover.details, {"reason": "dead_air"})

    def test_an_unknown_event_type_is_counted_as_rejected_not_raised(self):
        from core.relay_events import apply_event_batch

        counts = apply_event_batch([{"type": "not_a_real_event", "details": {}}])

        self.assertEqual(counts, {"accepted": 0, "rejected": 1})
        self.assertEqual(SystemEvent.objects.count(), 0)

    def test_an_event_without_a_channel_id_still_writes_a_row(self):
        from core.relay_events import apply_event_batch

        counts = apply_event_batch(
            [
                {
                    "type": "vod_start",
                    "channel_id": "",
                    "details": {
                        "content_name": "Movie Title",
                        "client_ip": "10.0.0.5",
                        "username": "alice",
                    },
                }
            ]
        )

        self.assertEqual(counts, {"accepted": 1, "rejected": 0})
        self.assertEqual(SystemEvent.objects.count(), 1)
        row = SystemEvent.objects.get()
        self.assertIsNone(row.channel_id)
        self.assertEqual(row.details["content_name"], "Movie Title")


class StreamStatsAreNotSystemEventsTests(TransactionTestCase):
    # TransactionTestCase, not TestCase: _apply_stream_stats calls the real
    # close_old_connections() unconditionally (moved verbatim from
    # ChannelService._update_stream_stats_in_db), which under test settings'
    # CONN_MAX_AGE=0 actually closes the live psycopg connection. A
    # TestCase's per-test atomic wrapper cannot survive that; a
    # TransactionTestCase's own connection reopens transparently on the
    # next query, and the write was already committed.
    def setUp(self):
        # A Stream fixture must carry its own M3UAccount: the kept test DB
        # can lose the migration-seeded "custom" row to an earlier
        # TransactionTestCase, and Stream's pre_save signal would then
        # raise trying to look it up.
        self.account = M3UAccount.objects.create(
            name="pr6-relay-events-account",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.stream = Stream.objects.create(
            name="pr6-relay-events-stream", m3u_account=self.account
        )

    def test_stream_stats_writes_the_stream_row_and_no_event_row(self):
        from core.relay_events import apply_event_batch

        counts = apply_event_batch(
            [
                {
                    "type": "stream_stats",
                    "stream_id": self.stream.id,
                    "details": {"ffmpeg_output_bitrate": 4200.0},
                }
            ]
        )

        self.assertEqual(counts, {"accepted": 1, "rejected": 0})
        self.assertEqual(SystemEvent.objects.count(), 0)

        self.stream.refresh_from_db()
        self.assertEqual(
            self.stream.stream_stats.get("ffmpeg_output_bitrate"), 4200.0
        )
        self.assertIsNotNone(self.stream.stream_stats_updated_at)

    def test_stream_stats_merges_rather_than_replaces(self):
        from core.relay_events import apply_event_batch

        self.stream.stream_stats = {"video_codec": "h264"}
        self.stream.save(update_fields=["stream_stats"])

        apply_event_batch(
            [
                {
                    "type": "stream_stats",
                    "stream_id": self.stream.id,
                    "details": {
                        "ffmpeg_output_bitrate": 4200.0,
                        "audio_codec": None,
                    },
                }
            ]
        )

        self.stream.refresh_from_db()
        self.assertEqual(self.stream.stream_stats.get("video_codec"), "h264")
        self.assertEqual(
            self.stream.stream_stats.get("ffmpeg_output_bitrate"), 4200.0
        )
        self.assertNotIn("audio_codec", self.stream.stream_stats)

    def test_stream_stats_releases_the_db_connection(self):
        from core.relay_events import apply_event_batch

        with patch("core.relay_events.close_old_connections") as mock_close:
            apply_event_batch(
                [
                    {
                        "type": "stream_stats",
                        "stream_id": self.stream.id,
                        "details": {"ffmpeg_output_bitrate": 1.0},
                    }
                ]
            )
        mock_close.assert_called_once()


class RelayEventWebSocketPushTests(TestCase):
    def test_only_the_three_ui_visible_types_push_a_relay_event(self):
        from core.relay_events import apply_event_batch

        channel_id = "22222222-2222-2222-2222-222222222222"
        with patch("core.relay_events.send_websocket_update") as mock_send:
            apply_event_batch(
                [
                    {
                        "type": "channel_failover",
                        "channel_id": channel_id,
                        "details": {},
                    },
                    {
                        "type": "stream_switch",
                        "channel_id": channel_id,
                        "details": {},
                    },
                    {
                        "type": "client_disconnect",
                        "channel_id": channel_id,
                        "details": {},
                    },
                    {
                        "type": "channel_start",
                        "channel_id": channel_id,
                        "details": {},
                    },
                ]
            )

        self.assertEqual(mock_send.call_count, 3)
        pushed_events = {call.args[2]["event"] for call in mock_send.call_args_list}
        self.assertEqual(
            pushed_events, {"channel_failover", "stream_switch", "client_disconnect"}
        )

    def test_the_relay_event_payload_is_a_whitelist(self):
        from core.relay_events import apply_event_batch

        channel_id = "33333333-3333-3333-3333-333333333333"
        with patch("core.relay_events.send_websocket_update") as mock_send:
            apply_event_batch(
                [
                    {
                        "type": "stream_switch",
                        "channel_id": channel_id,
                        "stream_id": 42,
                        "details": {
                            "new_url": "http://provider.example/secret/creds",
                            "reason": "manual",
                        },
                    }
                ]
            )

        mock_send.assert_called_once()
        payload = mock_send.call_args.args[2]
        self.assertNotIn("new_url", payload)
        self.assertNotIn("details", payload)
        self.assertEqual(payload["event"], "stream_switch")
        self.assertEqual(payload["channel_id"], channel_id)
        self.assertEqual(payload["stream_id"], 42)
