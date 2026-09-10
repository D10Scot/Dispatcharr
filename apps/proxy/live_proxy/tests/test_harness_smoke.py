"""The harness's own smoke test: a real tune, a real child process, real TS bytes.

This is the one file in the harness allowed to look at the relay's internals --
the pid of the spawned process, the StreamManager in ProxyServer's dict --
because its subject IS the harness. Every test from 2a-3 onward asserts on
observable behaviour only (bytes, status fields, events), per the spec's
composition rule.
"""

import os

from django.test import SimpleTestCase

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class HarnessSmokeTests(RelayHarnessTestCase):
    def test_a_tune_spawns_a_real_process_and_serves_real_ts_bytes(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            # Everything is asserted INSIDE the tune: the response staying open
            # is what keeps the channel from starting to tear down underneath
            # the assertions (channel_shutdown_delay defaults to 0).
            with self.tuned(channel) as stream:
                body = stream.read(20 * TS_PACKET_SIZE)

                assert_ts_aligned(body)
                self.assertEqual(len(body), 20 * TS_PACKET_SIZE)
                self.assertGreaterEqual(self.upstream.request_count, 1)

                pid = self.spawned_pid(channel)
                self.assertGreater(pid, 0)
                os.kill(pid, 0)  # raises OSError if it is not a live process

            self.stop_channel(channel)
            wait_until(
                lambda: not self.process_is_alive(pid),
                timeout=10,
                what=f"the spawned process {pid} to exit",
            )

    def test_the_control_plane_is_reachable_from_the_relay(self):
        """The relay's own HTTP call to Django lands, rather than degrading."""
        from core.models import SystemEvent

        before = SystemEvent.objects.count()
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            with self.tuned(channel) as stream:
                stream.read(4 * TS_PACKET_SIZE)
                pid = self.spawned_pid(channel)

            # Wait for the spawned process to actually exit, matching the
            # first test. Without this, whether input/manager.py's own EOF
            # handling runs at all before this test's own cleanup (fetch_chunk's
            # "Server closed connection" branch, _close_socket's stderr-reader
            # join and transcode-flag clear, _process_stream_data's retry
            # sleep) depends on a scheduling race between this thread and the
            # stream manager's background thread, not on anything this test
            # asserts -- and that race, not this test's own subject, is what
            # used to make the Task 7 gate's coverage move between runs.
            self.stop_channel(channel)
            wait_until(
                lambda: not self.process_is_alive(pid),
                timeout=10,
                what=f"the spawned process {pid} to exit",
            )

        wait_until(
            lambda: SystemEvent.objects.count() > before,
            timeout=10,
            what="a SystemEvent row written through POST /api/relay/events",
        )


class RealFfmpegTests(SimpleTestCase):
    def test_real_ffmpeg_remuxes_the_harness_asset(self):
        """The capability 2a-6 needs: bytes a real remuxer produced."""
        import subprocess

        from .harness.asset import build_real_ts_asset, ffmpeg_env, require_real_ffmpeg

        executable = require_real_ffmpeg()
        source = build_real_ts_asset(seconds=1.0)
        assert_ts_aligned(source)

        # The PRODUCTION command, minus its argv[0], so this test cannot drift
        # from what output/fmp4/manager.py actually spawns. Hand-writing the
        # argument list here loses `-bsf:a aac_adtstoasc`, and without it a real
        # AAC-in-MPEG-TS input dies with "Malformed AAC bitstream detected ...
        # Error muxing a packet" and exit 255 -- which is exactly the failure
        # FFMPEG_REMUX_CMD's own comment at :31 says the filter exists to avoid.
        from apps.proxy.live_proxy.output.fmp4.manager import FFMPEG_REMUX_CMD

        completed = subprocess.run(
            [executable] + list(FFMPEG_REMUX_CMD[1:]),
            input=source,
            capture_output=True,
            env=ffmpeg_env(),
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[:400])
        self.assertIn(b"moof", completed.stdout)
