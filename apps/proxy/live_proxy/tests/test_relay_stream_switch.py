"""A running channel switched to another source, and a client that joins late.

Matrix rows 7 and 8. Both drive ChannelService's switch path and the TS
generator's client-positioning path through the admin HTTP surface -- which is
what makes them portable: the Go relay serves the same two routes.
"""

import time

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, synthetic_ts
from .harness.control import ControlMixin, open_tune
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .harness.upstream import NOMINAL_BYTE_RATE, FakeUpstream

# synthetic_ts()'s default PID, and a second one so a client can tell which
# source a packet came from without decoding anything.
FIRST_PID = 0x100
SECOND_PID = 0x200
# Short enough that a test does not have to buffer five real seconds. The
# DEFAULT is asserted separately below -- this is the compressed value.
BEHIND_SECONDS = 0.5


def pids(data):
    """Every distinct PID in `data`, read from the 13 bits after the sync byte."""
    return {
        ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
        for offset in range(0, len(data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE)
    }


class SwitchTests(ControlMixin, RelayHarnessTestCase):
    def test_a_stream_switch_never_rewinds_the_chunk_index(self):
        """Matrix row 7.

        One client stays connected across the switch and reads both sources'
        packets out of the same ring buffer, while buffer_index only ever goes
        up. That is the whole claim: reset_buffer_position() clears
        _write_buffer and _partial_packet and never touches self.index
        (input/buffer.py:136-168), which is why a switch does not disturb a
        connected client.
        """
        second = FakeUpstream(payload=synthetic_ts(packets=512, pid=SECOND_PID)).start()
        self.addCleanup(second.stop)

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel) as stream:
                self.assertEqual(pids(stream.read(20 * TS_PACKET_SIZE)), {FIRST_PID})
                _, before = self.status(channel)

                response = self.change_stream(channel, second.url)
                self.assertEqual(response.status_code, 200)
                # The relay applied the switch itself rather than publishing it
                # for another worker: change_stream_url's owner branch, which
                # is where update_url() and reset_buffer_position() are called.
                self.assertIs(response.json()["owner"], True)

                # Read the index NOW, before any further read can absorb the
                # gap -- this assertion is the whole row and it has to happen
                # here. A rewind restarts the new source's INCR at 1 while the
                # client sits far above it, so the client simply receives
                # nothing until the new numbering overtakes the old: about half
                # a second at this pacing, which the 1500-packet read below
                # swallows whole, after which the index has climbed past its
                # old value again. Asserted at this point the rewind is a 0
                # against an 80; asserted after the read it is invisible.
                # Measured: with `self.index = 0` and a delete of the index key
                # added to reset_buffer_position, the version of this test
                # WITHOUT these three lines still passed.
                _, right_after = self.status(channel)
                self.assertGreaterEqual(
                    right_after["buffer_index"], before["buffer_index"]
                )

                # The metadata write lands before the reconnect does, so
                # waiting on the status url would wait for the wrong thing.
                # Wait for the new upstream to actually be connected.
                wait_until(
                    lambda: second.request_count >= 1,
                    timeout=10,
                    what="the relay to connect to the new upstream",
                )
                after_switch = stream.read(1500 * TS_PACKET_SIZE)
                _, after = self.status(channel)

            assert_ts_aligned(after_switch)
            self.assertIn(SECOND_PID, pids(after_switch))
            self.assertGreater(after["buffer_index"], before["buffer_index"])
            self.assertEqual(after["url"], second.url)
            self.stop_channel(channel)


class PositioningTests(ControlMixin, RelayHarnessTestCase):
    def test_a_new_client_starts_behind_live(self):
        """Matrix row 8.

        A client positioned at the buffer head can only receive bytes as fast
        as the upstream produces them. A client positioned `behind_seconds`
        back has a backlog sitting in Redis and drains it at loopback speed.
        The threshold is derived from the upstream's own pacing, never from a
        measurement: `live_would_take` is what the same bytes would have cost
        at the wire rate, and the test asserts the drain beat half of it.
        """
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        # The row says "roughly 5 seconds behind live", so pin the default
        # before compressing it -- otherwise nothing in this suite asserts the 5.
        TSConfig.clear_proxy_settings_cache()
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), 5)
        self.set_proxy_setting(new_client_behind_seconds=BEHIND_SECONDS)
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), BEHIND_SECONDS)

        bytes_per_second = self.upstream.rate * NOMINAL_BYTE_RATE
        chunks_for_the_window = int(
            BEHIND_SECONDS * bytes_per_second // TSConfig.BUFFER_CHUNK_SIZE
        )

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel) as first:
                first.read(4 * TS_PACKET_SIZE)
                # Twice the window, so find_chunk_index_by_time() has a chunk
                # old enough to answer with and does not fall through to its
                # oldest-available branch -- a different behaviour.
                wait_until(
                    lambda: self.status(channel)[1].get("buffer_index", 0)
                    >= 2 * chunks_for_the_window,
                    timeout=10,
                    what="twice the behind-live window to accumulate in the ring buffer",
                )

                _, joiner = open_tune(self, channel)
                started = time.monotonic()
                backlog = joiner.read(60 * TS_PACKET_SIZE)
                drained_in = time.monotonic() - started

            live_would_take = len(backlog) / bytes_per_second
            self.assertLess(drained_in, live_would_take / 2)
            self.stop_channel(channel)
