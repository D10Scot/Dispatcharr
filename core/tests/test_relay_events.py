"""core.relay_events.apply_event_batch — Phase 1 PR 6, Task 5.

The relay used to call log_system_event() at thirteen sites and
Stream.save() at one; both now arrive here as one batch posted to
POST /api/relay/events (Task 6). These tests exercise the writer directly,
without the view.
"""

from unittest.mock import patch

from django.test import TestCase

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

    def test_a_details_key_colliding_with_a_reserved_name_does_not_crash_the_batch(self):
        # control_plane.emit_event never puts channel_id/channel_name/
        # event_type inside details -- it binds them by name itself -- but
        # a hand-built batch (a Phase 2 relay, or a malformed request)
        # could, and log_system_event(event_type, channel_id=...,
        # channel_name=..., **details) would raise TypeError on the
        # duplicate keyword argument without the pop below. The real
        # top-level identity fields win; the colliding detail is dropped,
        # not stored, and every event in the batch is still accepted.
        from core.relay_events import apply_event_batch

        channel_id = "44444444-4444-4444-4444-444444444444"
        counts = apply_event_batch(
            [
                {
                    "type": "channel_start",
                    "channel_id": channel_id,
                    "details": {"channel_id": "spoofed-value"},
                },
                {
                    "type": "channel_failover",
                    "channel_id": channel_id,
                    "details": {"event_type": "spoofed-value"},
                },
            ]
        )

        self.assertEqual(counts, {"accepted": 2, "rejected": 0})
        self.assertEqual(SystemEvent.objects.count(), 2)
        for row in SystemEvent.objects.all():
            self.assertEqual(str(row.channel_id), channel_id)
            self.assertNotIn("channel_id", row.details)
            self.assertNotIn("event_type", row.details)

    def test_an_event_that_still_fails_the_write_is_rejected_not_fatal(self):
        # Defense in depth beyond the pop above: whatever else might make
        # log_system_event raise TypeError, one bad entry must not lose
        # the rest of the batch.
        from core.relay_events import apply_event_batch

        channel_id = "55555555-5555-5555-5555-555555555555"
        with patch(
            "core.relay_events.log_system_event",
            side_effect=[TypeError("boom"), None],
        ):
            counts = apply_event_batch(
                [
                    {"type": "channel_start", "channel_id": channel_id, "details": {}},
                    {"type": "channel_stop", "channel_id": channel_id, "details": {}},
                ]
            )

        self.assertEqual(counts, {"accepted": 1, "rejected": 1})


class StreamStatsAreNotSystemEventsTests(TestCase):
    # _apply_stream_stats calls the real close_old_connections()
    # unconditionally (moved verbatim from
    # ChannelService._update_stream_stats_in_db), which under test
    # settings' CONN_MAX_AGE=0 actually closes the live psycopg
    # connection -- fatal to a TestCase's atomic wrapper on the next
    # query. Every DB-effect test below patches it out, the same way
    # apps/proxy/tests/test_next_source_resolution.py patches
    # apps.proxy.next_source.close_old_connections. A TransactionTestCase
    # would dodge the same hazard, but every TransactionTestCase flushes
    # every table in a --keepdb database, stripping migration-seeded rows
    # for every later run in the same container -- the hazard the
    # implementer preamble itself warns about.
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

        with patch("core.relay_events.close_old_connections"):
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

        with patch("core.relay_events.close_old_connections"):
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

    def test_stream_id_is_never_stored_inside_stream_stats(self):
        # Task 10's emit_event("stream_stats", stream_id=stream_id, **stats)
        # copies stream_id to the top level of the event but leaves it in
        # details too -- it must not end up as a key inside
        # Stream.stream_stats, which today's
        # ChannelService._update_stream_stats_in_db(stream_id, **stats)
        # never stored.
        from core.relay_events import apply_event_batch

        with patch("core.relay_events.close_old_connections"):
            apply_event_batch(
                [
                    {
                        "type": "stream_stats",
                        "stream_id": self.stream.id,
                        "details": {
                            "stream_id": self.stream.id,
                            "ffmpeg_output_bitrate": 4200.0,
                        },
                    }
                ]
            )

        self.stream.refresh_from_db()
        self.assertNotIn("stream_id", self.stream.stream_stats)
        self.assertEqual(
            self.stream.stream_stats.get("ffmpeg_output_bitrate"), 4200.0
        )

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

    def test_the_push_falls_back_to_details_when_the_top_level_field_is_none(self):
        # Through the view, RelayEventSerializer's validated_data always
        # carries client_id/stream_id explicitly (None when the caller
        # omitted them), so a plain dict.get(field, details.get(field))
        # never actually reaches the details fallback: the key is present
        # with value None, not absent. This shape -- key present, value
        # None, the real value only in details -- is exactly what that
        # validated_data produces for a field the caller left out.
        from core.relay_events import apply_event_batch

        channel_id = "66666666-6666-6666-6666-666666666666"
        with patch("core.relay_events.send_websocket_update") as mock_send:
            apply_event_batch(
                [
                    {
                        "type": "client_disconnect",
                        "channel_id": channel_id,
                        "client_id": None,
                        "details": {"client_id": "client-42"},
                    }
                ]
            )

        mock_send.assert_called_once()
        payload = mock_send.call_args.args[2]
        self.assertEqual(payload["client_id"], "client-42")
