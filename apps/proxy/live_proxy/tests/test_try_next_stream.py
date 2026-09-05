"""_try_next_stream asks Django for its next source (Phase 1 PR 6, Task 8).

A hand-built StreamManager-shaped object is the only practical fixture
here (test_vlc_failover.py's own StreamManager.__new__(StreamManager)
pattern, copied rather than reinvented) -- __init__ wants a real buffer,
Redis and ConfigHelper reads that this unit has no business exercising.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy import control_plane
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.input import manager as manager_module
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys


def make_manager(channel_id="chan-1", url="http://current", current_stream_id=1,
                  tried=None):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = channel_id
    sm.channel_name = "Test Channel"
    sm.url = url
    sm.current_stream_id = current_stream_id
    sm.tried_stream_ids = set(tried or ([current_stream_id] if current_stream_id else []))
    sm.user_agent = "old-agent"
    sm.transcode = False
    sm._failover_degraded = False
    sm.buffer = MagicMock()
    sm.buffer.redis_client = MagicMock()
    sm.update_url = MagicMock(return_value=True)
    return sm


def make_source(stream_id=2, url="http://next", profile_id=99, m3u_profile_id=None,
                 user_agent="new-agent", transcode=True):
    return {
        "stream_id": stream_id,
        "url": url,
        "user_agent": user_agent,
        "transcode": transcode,
        "stream_profile": {"id": profile_id, "command": "ffmpeg", "args": []},
        "m3u_profile_id": m3u_profile_id if m3u_profile_id is not None else 55,
        "slot_reserved": True,
    }


class TryNextStreamTests(TestCase):
    def test_failover_makes_one_next_source_call_carrying_what_it_has_tried(self):
        sm = make_manager(current_stream_id=1, tried={1, 7})
        answer = {"source": make_source(stream_id=2), "alternates": [], "error": None}

        with patch("apps.proxy.control_plane.next_source", return_value=answer) as mock_next:
            result = sm._try_next_stream()

        self.assertTrue(result)
        mock_next.assert_called_once()
        args, kwargs = mock_next.call_args
        self.assertEqual(args[0], sm.channel_id)
        self.assertEqual(sorted(kwargs["exclude_stream_ids"]), [1, 7])
        self.assertEqual(kwargs["current_url"], "http://current")
        self.assertEqual(kwargs["current_stream_id"], 1)
        self.assertEqual(kwargs["reason"], "failover")

    def test_failover_with_no_known_current_stream_id_still_passes_it_through(self):
        # Review round 1, Blocking: current_stream_id must reach next_source
        # even when it is None (nothing tried yet, no stream id loaded) --
        # the client then omits it from the request body, and Django's
        # resolve_source routes on current_url/reason instead of on
        # exclude_stream_ids alone (Important finding, fixed in
        # next_source.py) so this case still reaches the failover traversal
        # rather than replaying the URL already playing.
        sm = make_manager(current_stream_id=None, tried=set())
        answer = {"source": make_source(stream_id=2), "alternates": [], "error": None}

        with patch("apps.proxy.control_plane.next_source", return_value=answer) as mock_next:
            result = sm._try_next_stream()

        self.assertTrue(result)
        args, kwargs = mock_next.call_args
        self.assertEqual(kwargs["exclude_stream_ids"], [])
        self.assertIsNone(kwargs["current_stream_id"])

    def test_the_returned_source_is_applied_without_a_second_call(self):
        sm = make_manager(current_stream_id=1, tried={1})
        source = make_source(stream_id=2, url="http://next", profile_id=99,
                              m3u_profile_id=55, user_agent="new-agent", transcode=True)
        answer = {"source": source, "alternates": [], "error": None}

        with patch("apps.proxy.control_plane.next_source", return_value=answer) as mock_next:
            result = sm._try_next_stream()

        self.assertTrue(result)
        mock_next.assert_called_once()
        sm.update_url.assert_called_once_with("http://next", 2, 55)
        self.assertEqual(sm.current_stream_id, 2)
        self.assertEqual(sm.user_agent, "new-agent")
        self.assertTrue(sm.transcode)

        metadata_key = RedisKeys.channel_metadata(sm.channel_id)
        hset_calls = [
            call for call in sm.buffer.redis_client.hset.call_args_list
            if call.args and call.args[0] == metadata_key
        ]
        self.assertEqual(len(hset_calls), 1)
        mapping = hset_calls[0].kwargs["mapping"]
        self.assertEqual(mapping[ChannelMetadataField.STREAM_ID], "2")
        self.assertEqual(mapping[ChannelMetadataField.M3U_PROFILE], "55")
        self.assertEqual(mapping[ChannelMetadataField.STREAM_PROFILE], "99")
        self.assertIn(ChannelMetadataField.STREAM_SWITCH_TIME, mapping)
        self.assertIn(ChannelMetadataField.STREAM_SWITCH_REASON, mapping)

    def test_no_source_left_returns_false(self):
        sm = make_manager()
        answer = {"source": None, "alternates": [], "error": "No alternate stream with available connections"}

        with patch("apps.proxy.control_plane.next_source", return_value=answer):
            result = sm._try_next_stream()

        self.assertFalse(result)
        sm.update_url.assert_not_called()
        sm.buffer.redis_client.hset.assert_not_called()

    def test_the_degraded_path_uses_the_cached_alternates_and_reserves_nothing(self):
        sm = make_manager(current_stream_id=1, tried={1})
        cached = [
            make_source(stream_id=3, url="http://cached-3"),
            make_source(stream_id=4, url="http://cached-4"),
        ]

        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneUnavailable("down")), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates",
                   return_value=cached) as mock_cached, \
             patch("apps.proxy.control_plane.release_source") as mock_release, \
             self.assertLogs(manager_module.logger, level="WARNING"):
            result = sm._try_next_stream()

        self.assertTrue(result)
        mock_cached.assert_called_once_with(sm.channel_id)
        sm.update_url.assert_called_once_with("http://cached-3", 3, cached[0]["m3u_profile_id"])
        mock_release.assert_not_called()
        self.assertTrue(sm._failover_degraded)

    def test_the_degraded_path_skips_the_current_url(self):
        sm = make_manager(current_stream_id=1, tried={1}, url="http://cached-3")
        cached = [
            make_source(stream_id=3, url="http://cached-3"),
            make_source(stream_id=4, url="http://cached-4"),
        ]

        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneUnavailable("down")), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates",
                   return_value=cached), \
             self.assertLogs(manager_module.logger, level="WARNING"):
            result = sm._try_next_stream()

        self.assertTrue(result)
        sm.update_url.assert_called_once_with("http://cached-4", 4, cached[1]["m3u_profile_id"])

    def test_a_channel_error_event_is_posted_once_django_answers_again(self):
        sm = make_manager(current_stream_id=1, tried={1})
        cached = [make_source(stream_id=3, url="http://cached-3")]

        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneUnavailable("down")), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates",
                   return_value=cached), \
             self.assertLogs(manager_module.logger, level="WARNING"):
            self.assertTrue(sm._try_next_stream())
        self.assertTrue(sm._failover_degraded)

        source = make_source(stream_id=9, url="http://back-on-django")
        answer = {"source": source, "alternates": [], "error": None}
        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch.object(manager_module, "emit_event") as mock_emit:
            self.assertTrue(sm._try_next_stream())

        self.assertFalse(sm._failover_degraded)
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        self.assertEqual(args[0], "channel_error")
        self.assertEqual(kwargs.get("channel_id") or (args[1] if len(args) > 1 else None), sm.channel_id)
        self.assertEqual(kwargs.get("reason"), "degraded_failover")

    def test_a_404_ends_the_switch_attempt_rather_than_degrading(self):
        sm = make_manager()
        answer = {"source": None, "alternates": [], "error": "identifier not found"}

        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates") as mock_cached:
            result = sm._try_next_stream()

        self.assertFalse(result)
        mock_cached.assert_not_called()
        sm.update_url.assert_not_called()

    def test_a_403_never_triggers_the_degraded_fallback(self):
        sm = make_manager()

        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneRefused(403, "/api/relay/x")), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates") as mock_cached, \
             self.assertLogs(manager_module.logger, level="ERROR") as logs:
            result = sm._try_next_stream()

        self.assertFalse(result)
        mock_cached.assert_not_called()
        sm.update_url.assert_not_called()
        self.assertTrue(any("403" in message for message in logs.output))

    def test_the_degraded_path_skips_a_cached_entry_missing_required_fields(self):
        sm = make_manager(current_stream_id=1, tried={1})
        corrupt = {"stream_id": 3, "url": "http://cached-3"}  # no user_agent/transcode/m3u_profile_id
        good = make_source(stream_id=4, url="http://cached-4")

        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneUnavailable("down")), \
             patch("apps.proxy.live_proxy.url_utils.read_cached_alternates",
                   return_value=[corrupt, good]), \
             self.assertLogs(manager_module.logger, level="WARNING"):
            result = sm._try_next_stream()

        self.assertTrue(result)
        sm.update_url.assert_called_once_with("http://cached-4", 4, good["m3u_profile_id"])

    def test_a_metadata_write_failure_does_not_unwind_an_applied_switch(self):
        sm = make_manager(current_stream_id=1, tried={1})
        sm.buffer.redis_client.hset.side_effect = RuntimeError("redis down")
        answer = {"source": make_source(stream_id=2), "alternates": [], "error": None}

        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             self.assertLogs(manager_module.logger, level="ERROR"):
            result = sm._try_next_stream()

        self.assertTrue(result)
        self.assertEqual(sm.current_stream_id, 2)
