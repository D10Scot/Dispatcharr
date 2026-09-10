"""The fMP4 output path, end to end, against a REAL ffmpeg remux.

FMP4RemuxManager parses moof boxes out of its child's stdout
(output/fmp4/manager.py:316-332) and a dumb pipe carrying MPEG-TS contains
none, so a stand-in remux stores no init segment, _wait_for_fmp4_ready polls
for INIT_SEGMENT_TIMEOUT (15s) and the client gets an empty 200. See the 2a-6
plan's F1. Nothing in this file may use StandInBin as the remux child; the
INPUT child (the Stream Profile feeding the ring buffer) is still a stand-in,
via standin_stream_profile(), which does not shadow `ffmpeg` on PATH.
"""

import os
import shutil
import tempfile
from unittest.mock import patch

from core.models import OutputProfile

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.asset import TS_PACKET_SIZE
from .harness.relay import RelayHarnessTestCase
from .manager_support import proxy_stream_profile
from .output_support import (
    assert_fmp4_init_then_fragment,
    fragmentable_upstream_payload,
    real_ffmpeg_environment,
    spawn_count,
    spawn_logging_standin,
    standin_stream_profile,
    tapped,
    wait_for_bytes,
)


class FMP4OutputTests(RelayHarnessTestCase):
    """The fMP4 output path against a REAL ffmpeg remux.

    Real ffmpeg, not the stand-in, and the reason is structural rather than a
    preference: FMP4RemuxManager parses moof boxes out of its child's stdout
    (output/fmp4/manager.py:316-332) and a dumb pipe carrying MPEG-TS contains
    none, so a stand-in remux stores no init segment, _wait_for_fmp4_ready polls
    for INIT_SEGMENT_TIMEOUT (15s) and the client gets an empty 200. See the 2a-6
    plan's F1.
    """

    def setUp(self):
        super().setUp()
        self.enterContext(real_ffmpeg_environment())
        # A real TS asset, and a bigger chunk than the base class's 1,880 bytes:
        # this test moves megabytes rather than kilobytes and 1,880-byte chunks
        # would put thousands of keys into the shared DB 0 (harness/README.md's
        # second trap). 37,600 bytes at 500 KB/s is a chunk every 75ms, still far
        # below anything a client waits on.
        self.upstream.payload = fragmentable_upstream_payload()
        self.upstream.rate = 2.0
        self.enterContext(patch.object(TSConfig, "BUFFER_CHUNK_SIZE", TS_PACKET_SIZE * 200))

    def test_an_fmp4_client_receives_an_init_segment_and_fragments(self):
        directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        profile = standin_stream_profile(directory, name="fmp4-input")
        channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

        with tapped(self, channel) as ts_client:
            wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
            with tapped(self, channel, "?output_format=fmp4") as fmp4_client:
                # 14s, deliberately under INIT_SEGMENT_TIMEOUT's 15: past that the
                # generator gives up and returns an empty 200, and the failure would
                # read as "no bytes" instead of "the remux never produced an init
                # segment". Measured end-to-end at 1.69s against a 250 KB/s feed.
                wait_for_bytes(self, fmp4_client, 40_000, timeout=14.0, what="fMP4 bytes")
                assert_fmp4_init_then_fragment(self, fmp4_client.snapshot())
        self.stop_channel(channel)

    def test_a_second_fmp4_client_joins_the_running_remux(self):
        directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        profile = standin_stream_profile(directory, name="fmp4-input")
        channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

        with tapped(self, channel) as ts_client:
            wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
            with tapped(self, channel, "?output_format=fmp4") as first:
                wait_for_bytes(self, first, 40_000, timeout=14.0, what="fMP4 bytes for the first client")
                with tapped(self, channel, "?output_format=fmp4") as second:
                    wait_for_bytes(self, second, 40_000, timeout=14.0, what="fMP4 bytes for the second client")
                    assert_fmp4_init_then_fragment(self, second.snapshot())

                    # The second client is served from the SAME remux: to count
                    # spawns here the child must be the real ffmpeg, so Task 3's
                    # spawn-log trick is not available (it would shadow `ffmpeg`
                    # on PATH and break the remux itself). Assert the sharing
                    # through the owner lock instead -- one key, one value. This
                    # is row 11's spawn-count pin's fMP4 sibling, deliberately
                    # weaker.
                    owner_key = RedisKeys.output_owner(str(channel.uuid), "fmp4")
                    self.assertEqual(
                        ProxyServer.get_instance().redis_client.get(owner_key),
                        ProxyServer.get_instance().worker_id,
                        "the fMP4 remux owner lock moved between the two clients",
                    )
        self.stop_channel(channel)

    def test_an_fmp4_client_on_an_output_profile_gets_its_own_pipeline(self):
        """The `fmp4:p<id>` compound key: a distinct path through views.py:696-699,
        ProxyServer._parse_output_key and ensure_output_format's source_buffer
        argument. Cheap here because the two children compose: the Output
        Profile's child is a stand-in dumb pipe passing real TS through, and the
        fMP4 remux's child is the bare `ffmpeg` from PATH (real). Uses the Proxy
        input profile: with an Output Profile in play there is no need for an
        input child, and one fewer process is one fewer thing to go wrong.
        """
        directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        log = os.path.join(directory, "profile-spawns.log")
        executable = spawn_logging_standin(directory, log, name="profile-standin")
        output = OutputProfile.objects.create(
            name="harness-output-profile-fmp4",
            command=executable,
            parameters="-i pipe:0 -f mpegts pipe:1",
            is_active=True,
        )
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        query = f"?output_format=fmp4&output_profile={output.id}"

        with tapped(self, channel, query) as client:
            wait_for_bytes(self, client, 40_000, timeout=14.0, what="fMP4 bytes")
            assert_fmp4_init_then_fragment(self, client.snapshot())
            self.assertEqual(spawn_count(log), 1, "the Output Profile transcode did not start exactly once")
            # The compound key is the point of this test: the remux runs under
            # `fmp4:p<id>`, not `fmp4`, and reads the PROFILE's buffer rather than
            # the raw TS buffer (views.py:696-699, :736-739, :756).
            redis_client = ProxyServer.get_instance().redis_client
            self.assertTrue(
                redis_client.exists(RedisKeys.output_state(str(channel.uuid), f"fmp4:p{output.id}")),
                "no fMP4 state key under the compound format key",
            )
            self.assertFalse(
                redis_client.exists(RedisKeys.output_state(str(channel.uuid), "fmp4")),
                "a bare `fmp4` remux started as well as the profile-scoped one",
            )
        self.stop_channel(channel)
