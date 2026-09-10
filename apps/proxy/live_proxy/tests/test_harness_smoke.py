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
    # exit_after_bytes for test 1's stand-in: large enough that the read
    # below (and the pid capture before it) reliably lands before the child's
    # own exit, small enough that the exit still happens well inside this
    # test's own run -- see the comment inside the test for why this needs to
    # be a WAITED-FOR event, not an assumed one.
    _NATURAL_END_BYTES = 2000 * TS_PACKET_SIZE

    def test_a_tune_spawns_a_real_process_and_serves_real_ts_bytes(self):
        # exit_after_bytes gives the stand-in a NATURAL end. That is what
        # makes input/manager.py's EOF-handling path deterministic
        # (fetch_chunk's "Server closed connection" branch at :1828-1831,
        # _close_socket's stderr-reader join and transcode-flag clear at
        # :1739-1767, _process_stream_data's retry sleep at :1329): the
        # relay's own background thread observes the child's own exit
        # whenever it next polls the pipe, independent of whether or when
        # this test calls stop_channel(). Relying on stop_channel()'s kill to
        # trigger this instead is what made the Task 7 gate move between
        # runs even after both smoke tests waited for the child to exit
        # AFTER calling stop_channel(): stop() sets stop_requested before it
        # kills the child, so the background thread's own read loop can --
        # and, measured over ten runs, sometimes does -- exit on that flag
        # without calling fetch_chunk() again, never observing the EOF the
        # kill was about to cause. A margin alone does not fix this either:
        # an earlier attempt at a 10-packet margin failed consistently,
        # because the relay's own setup (DB round trips, spawning the child,
        # waiting for the first buffer chunk to close) costs more wall clock
        # than a few packets take to produce at this test's paced upstream --
        # the child had already exited and been reaped before the test's own
        # first read even returned. What actually removes the race is
        # WAITING for the natural exit explicitly, below, rather than
        # assuming a byte margin bought enough time for it to already have
        # happened, or delegating it to stop_channel()'s kill.
        with self.stand_in(exit_after_bytes=self._NATURAL_END_BYTES):
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            # Everything up to the read is asserted INSIDE the tune: the
            # response staying open is what keeps the channel from starting
            # to tear down underneath the assertions (channel_shutdown_delay
            # defaults to 0).
            with self.tuned(channel) as stream:
                pid = self.spawned_pid(channel)
                self.assertGreater(pid, 0)
                os.kill(pid, 0)  # raises OSError if it is not a live process

                body = stream.read(20 * TS_PACKET_SIZE)

                assert_ts_aligned(body)
                self.assertEqual(len(body), 20 * TS_PACKET_SIZE)
                self.assertGreaterEqual(self.upstream.request_count, 1)

            # The stand-in keeps producing after the client disconnects (the
            # relay's background thread reads it regardless), and exits on
            # its own once it has copied _NATURAL_END_BYTES. Wait for THAT --
            # not for stop_channel() -- so the EOF-handling path above is
            # exercised deterministically before any kill enters the
            # picture.
            wait_until(
                lambda: not self.process_is_alive(pid),
                timeout=10,
                what=f"the spawned process {pid} to exit on its own (exit_after_bytes)",
            )

            # Only now does stop_channel() run, against an already-dead
            # process: this exercises the bookkeeping's idempotency (the
            # EOF-triggered _close_socket() already claimed
            # transcode_process = None) rather than the kill path itself --
            # a genuine race between stop()'s kill and the background
            # thread's own read loop, not something a test can pin down
            # without reaching into the relay's internals to synchronize
            # with it.
            self.stop_channel(channel)

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
