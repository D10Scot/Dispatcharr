"""PIN for Phase 2 PR 2b-1: the force-ffmpeg reconnect path takes its
StreamProfile from the channel metadata hash, not from a query.

Spec § Stage 2b, the input/manager.py:737 row. force_ffmpeg is set in
_run's main loop when detect_stream_type() sees an HLS, RTSP/RTP or UDP
upstream on a non-transcoding profile (input/manager.py:442-450), which is
why this test sets the flag directly rather than driving a real HLS tune:
the subject is which PROFILE the branch picks, not how the flag gets set.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.input.manager import StreamManager

# A marker no real DB-resolved profile would carry -- if the built command
# contains this, the profile came from the hash, not from
# channel.get_stream_profile().
HASH_MARKER = "-metadata from_the_hash=1"


def _make_manager(channel_id="chan-uuid", url="http://upstream/stream.ts", user_agent="UA"):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = channel_id
    sm.force_ffmpeg = True
    sm.transcode_process = None
    sm.current_response = None
    sm.current_session = None
    sm.url = url
    sm.user_agent = user_agent
    sm.buffer = MagicMock()
    sm.buffer.redis_client = MagicMock()
    return sm


class ForcedFfmpegProfileTests(SimpleTestCase):
    def _run_with_stored(self, sm, hash_value):
        """Drive _establish_transcode_connection far enough to build the
        command, then let a fake posix_spawn fail so the test never runs a
        real subprocess. transcode_cmd/stream_command are set before the
        spawn attempt, which is everything this PIN needs."""
        sm.buffer.redis_client.hget.return_value = hash_value
        channel = MagicMock()
        channel.id = 42
        channel.get_stream_profile.return_value = MagicMock(
            name="channel-default", command="channel-default-cmd", parameters="",
        )
        with patch(
            "apps.proxy.live_proxy.input.manager.get_stream_object",
            return_value=channel,
        ), patch("os.posix_spawn", side_effect=OSError("no real spawn in this test")), \
             patch.object(sm, "_close_socket"):
            sm._establish_transcode_connection()

    def test_the_stored_profile_is_used_when_present(self):
        """PIN. The hash's command/args reach build_command() verbatim."""
        sm = _make_manager()
        stored = json.dumps(
            {"id": 9, "command": "ffmpeg", "args": f"-i {{streamUrl}} {HASH_MARKER}"}
        ).encode()
        self._run_with_stored(sm, stored)

        self.assertEqual(sm.stream_command, "ffmpeg")
        self.assertEqual(sm.transcode_cmd[0], "ffmpeg")
        self.assertIn(sm.url, sm.transcode_cmd)
        self.assertIn(HASH_MARKER, " ".join(sm.transcode_cmd))

    def test_falls_back_to_the_channel_profile_when_the_hash_field_is_absent(self):
        """PIN. A deployment mid-upgrade (relay newer than Django, or a
        next-source answer that predates 2b-1) must not lose its forced
        remux -- same fallback the old StreamProfile.DoesNotExist branch took."""
        sm = _make_manager()
        self._run_with_stored(sm, None)

        self.assertEqual(sm.stream_command, "channel-default-cmd")
        self.assertNotIn(HASH_MARKER, " ".join(sm.transcode_cmd))

    def test_build_command_still_runs_for_the_stored_profile(self):
        """PIN, against a real gap the first break-check below exposed: a
        stored profile with locked=False would answer is_proxy()/
        is_redirect() no differently (both check locked AND name), so that
        alone can't be what keeps a Proxy/Redirect row's empty
        build_command() from slipping through this path. This asserts the
        built command is non-empty, which a real Proxy/Redirect profile's
        build_command() never is."""
        sm = _make_manager()
        stored = json.dumps(
            {"id": 9, "command": "ffmpeg", "args": "-i {streamUrl} -c copy -f mpegts pipe:1"}
        ).encode()
        self._run_with_stored(sm, stored)

        self.assertTrue(sm.transcode_cmd)
