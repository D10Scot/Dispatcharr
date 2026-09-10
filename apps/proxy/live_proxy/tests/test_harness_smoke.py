"""The harness's own smoke test: a real tune, a real child process, real TS bytes.

This is the one file in the harness allowed to look at the relay's internals --
the pid of the spawned process, the StreamManager in ProxyServer's dict --
because its subject IS the harness. Every test from 2a-3 onward asserts on
observable behaviour only (bytes, status fields, events), per the spec's
composition rule.
"""

import os

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import StandInBin, stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class HarnessSmokeTests(RelayHarnessTestCase):
    def test_a_tune_spawns_a_real_process_and_serves_real_ts_bytes(self):
        with StandInBin():
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
        with StandInBin():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            self.tune(channel, read_bytes=4 * TS_PACKET_SIZE)
            self.stop_channel(channel)

        wait_until(
            lambda: SystemEvent.objects.count() > before,
            timeout=10,
            what="a SystemEvent row written through POST /api/relay/events",
        )
