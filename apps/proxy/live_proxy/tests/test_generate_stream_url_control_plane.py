"""Pins generate_stream_url's control-plane body and the two cache helpers
(Phase 1 PR 6, Task 7 minor fixes riding on Task 8's file set).

generate_stream_url() (apps/proxy/live_proxy/url_utils.py) is a thin
wrapper around apps.proxy.control_plane.next_source(): these tests pin
its exact 7-tuple on every control-plane outcome (Phase 2 PR 2b-1 widened
it from 6 to carry the four Source names), and the two cache helpers
(_cache_alternates / read_cached_alternates) it and the Redirect-alternates
loop in views.py share.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy import control_plane
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.url_utils import (
    _cache_alternates,
    generate_stream_url,
    read_cached_alternates,
)


def make_source(stream_id=1, url="http://source", profile_id=7, m3u_profile_id=42,
                 user_agent="ua", transcode=True, slot_reserved=True):
    return {
        "stream_id": stream_id,
        "url": url,
        "user_agent": user_agent,
        "transcode": transcode,
        "stream_profile": {"id": profile_id, "command": "ffmpeg", "args": []},
        "m3u_profile_id": m3u_profile_id,
        "slot_reserved": slot_reserved,
    }


_NULL_EXTRAS = {
    "channel_name": None, "stream_name": None,
    "m3u_profile_name": None, "ffmpeg_stream_profile": None,
}


class GenerateStreamUrlControlPlaneBodyTests(SimpleTestCase):
    def test_success_returns_the_7_tuple_and_caches_alternates(self):
        source = make_source()
        answer = {"source": source, "alternates": [{"stream_id": 2}], "error": None}

        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils._cache_alternates") as mock_cache:
            result = generate_stream_url("chan-1")

        self.assertEqual(
            result,
            ("http://source", "ua", True, 7, True, None, _NULL_EXTRAS),
        )
        mock_cache.assert_called_once_with("chan-1", [{"stream_id": 2}])

    def test_no_source_returns_the_error_reason_with_no_url(self):
        answer = {"source": None, "alternates": [], "error": "No alternate stream with available connections"}

        with patch("apps.proxy.control_plane.next_source", return_value=answer):
            result = generate_stream_url("chan-1")

        self.assertEqual(
            result,
            (None, None, False, None, False, "No alternate stream with available connections", _NULL_EXTRAS),
        )

    def test_control_plane_unavailable_returns_no_url_and_the_exact_message(self):
        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneUnavailable("down")):
            result = generate_stream_url("chan-1")

        self.assertEqual(
            result,
            (None, None, False, None, False, "Control plane unreachable", _NULL_EXTRAS),
        )

    def test_control_plane_refused_returns_no_url_and_the_exact_message(self):
        with patch("apps.proxy.control_plane.next_source",
                   side_effect=control_plane.ControlPlaneRefused(403, "/api/relay/x")):
            result = generate_stream_url("chan-1")

        self.assertEqual(
            result,
            (None, None, False, None, False, "Control plane refused this channel", _NULL_EXTRAS),
        )

    def test_the_seventh_element_carries_the_names_and_the_ffmpeg_profile(self):
        """PIN. generate_stream_url is the only thing between the next-source
        answer and the relay's init call; a name dropped here is a name the
        relay re-queries for."""
        source = make_source()
        source.update(
            channel_name="BBC One",
            stream_name="BBC One HD",
            m3u_profile_name="Provider A default",
            ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
        )
        answer = {"source": source, "alternates": [], "error": None}
        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils._cache_alternates"):
            result = generate_stream_url("chan-1")
        self.assertEqual(
            result[6],
            {
                "channel_name": "BBC One",
                "stream_name": "BBC One HD",
                "m3u_profile_name": "Provider A default",
                "ffmpeg_stream_profile": {"id": 9, "command": "ffmpeg", "args": "-i x"},
            },
        )

    def test_an_old_django_answering_without_the_names_gives_a_dict_of_nulls(self):
        """PIN. The relay and the control plane are separately deployable
        processes (D5); a next-source answer from a Django that predates this
        PR must not KeyError on the byte path."""
        answer = {"source": make_source(), "alternates": [], "error": None}
        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils._cache_alternates"):
            result = generate_stream_url("chan-1")
        self.assertEqual(result[6], _NULL_EXTRAS)


class CacheAlternatesTests(SimpleTestCase):
    def test_stores_alternates_with_the_default_ttl(self):
        client = MagicMock()
        with patch("core.utils.RedisClient.get_client", return_value=client):
            _cache_alternates("chan-1", [{"stream_id": 2}])

        client.set.assert_called_once_with(
            RedisKeys.channel_source_cache("chan-1"),
            json.dumps([{"stream_id": 2}]),
            ex=3600,
        )
        client.delete.assert_not_called()

    def test_an_empty_answer_clears_the_cached_key_rather_than_leaving_it_stale(self):
        client = MagicMock()
        with patch("core.utils.RedisClient.get_client", return_value=client):
            _cache_alternates("chan-1", [])

        client.delete.assert_called_once_with(RedisKeys.channel_source_cache("chan-1"))
        client.set.assert_not_called()

    def test_no_redis_client_is_silently_a_no_op(self):
        with patch("core.utils.RedisClient.get_client", return_value=None):
            _cache_alternates("chan-1", [])  # must not raise
            _cache_alternates("chan-1", [{"stream_id": 2}])  # must not raise

    def test_a_redis_error_is_swallowed(self):
        client = MagicMock()
        client.set.side_effect = RuntimeError("redis down")
        with patch("core.utils.RedisClient.get_client", return_value=client):
            _cache_alternates("chan-1", [{"stream_id": 2}])  # must not raise


class ReadCachedAlternatesTests(SimpleTestCase):
    def test_reads_back_what_was_cached(self):
        client = MagicMock()
        client.get.return_value = json.dumps([{"stream_id": 2}]).encode()
        with patch("core.utils.RedisClient.get_client", return_value=client):
            result = read_cached_alternates("chan-1")

        self.assertEqual(result, [{"stream_id": 2}])
        client.get.assert_called_once_with(RedisKeys.channel_source_cache("chan-1"))

    def test_no_redis_client_returns_an_empty_list(self):
        with patch("core.utils.RedisClient.get_client", return_value=None):
            self.assertEqual(read_cached_alternates("chan-1"), [])

    def test_a_missing_key_returns_an_empty_list(self):
        client = MagicMock()
        client.get.return_value = None
        with patch("core.utils.RedisClient.get_client", return_value=client):
            self.assertEqual(read_cached_alternates("chan-1"), [])

    def test_a_non_list_payload_returns_an_empty_list(self):
        client = MagicMock()
        client.get.return_value = json.dumps({"not": "a list"}).encode()
        with patch("core.utils.RedisClient.get_client", return_value=client):
            self.assertEqual(read_cached_alternates("chan-1"), [])

    def test_corrupt_json_returns_an_empty_list_rather_than_raising(self):
        client = MagicMock()
        client.get.return_value = b"not json"
        with patch("core.utils.RedisClient.get_client", return_value=client):
            self.assertEqual(read_cached_alternates("chan-1"), [])
