"""A running channel switched to another source, and a client that joins late.

Matrix rows 7 and 8. Both drive ChannelService's switch path and the TS
generator's client-positioning path through the admin HTTP surface -- which is
what makes them portable: the Go relay serves the same two routes.
"""

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, packet_index, synthetic_ts
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
# How many packets PositioningTests' own upstream payload lays down.
# Comfortably above what the test produces within its own budget (a couple
# of seconds at NOMINAL_BYTE_RATE's pacing, well under 3,000 packets with
# margin), so the payload the fake upstream loops never wraps back to
# packet index 0 mid-test -- see synthetic_ts()'s docstring for why a wrap
# would make a packet's index ambiguous with an earlier one.
POSITION_PACKETS = 6000


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

        Row 8's claim is not just THAT a joining client starts behind live,
        but roughly HOW MUCH: assert the quantity of already-produced
        backlog the joiner is handed, not the time it takes to drain it. A
        quantity distinguishes all three of _setup_streaming's code paths at
        once -- positioned at the live head (backlog ~ 0 packets),
        positioned through chunk_timestamps (backlog ~ the configured
        window), or falling back to the oldest available chunk when there is
        not yet enough buffered history (backlog ~ everything produced so
        far, ordinarily many times the window).

        Elapsed read time cannot distinguish any of those in this harness.
        The fake upstream genuinely IS paced (FakeUpstream writes at
        rate * NOMINAL_BYTE_RATE), but the relay reads ahead of any client
        into Redis and the generator serves a client from there, so a
        client's own read is never throttled by that pacing and drains
        near-instantly regardless of where it started (harness/README.md,
        "Three traps for the tests that come next"). It is also a margin
        problem, not a strictly impossible one: 60 packets is barely more
        than one paced write burst, so an under-margined timing assertion
        mostly does not fire against a real break rather than never firing
        -- measured 1 red of 5 runs, which is worse in a suite than being
        simply wrong, because it still looks like coverage.

        Content PRESENCE alone is not enough either: synthetic_ts()'s old
        payload repeated every 256 packets, so "this content appeared
        somewhere earlier" was true even for the newest packet -- proving
        nothing about position. Its packet_index() (harness/asset.py) is
        unambiguous at any distance instead, so a packet's true position is
        read directly off the wire, the same way a client encounters it.
        """
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        # The row says "roughly 5 seconds behind live", so pin the default
        # before compressing it -- otherwise nothing in this suite asserts the 5.
        TSConfig.clear_proxy_settings_cache()
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), 5)
        self.set_proxy_setting(new_client_behind_seconds=BEHIND_SECONDS)
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), BEHIND_SECONDS)

        bytes_per_second = NOMINAL_BYTE_RATE  # the positioning upstream's own rate is 1.0
        packets_per_chunk = TSConfig.BUFFER_CHUNK_SIZE // TS_PACKET_SIZE
        chunks_for_the_window = int(
            BEHIND_SECONDS * bytes_per_second // TSConfig.BUFFER_CHUNK_SIZE
        )
        packets_for_the_window = chunks_for_the_window * packets_per_chunk

        positioned = FakeUpstream(payload=synthetic_ts(packets=POSITION_PACKETS)).start()
        self.addCleanup(positioned.stop)

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=positioned.url, profile=profile)
            with self.tuned(channel) as first:
                first.read(4 * TS_PACKET_SIZE)
                # Three times the window, not one: the exact packet count
                # this waits for is not load-bearing on its own, since the
                # live-head estimate below is re-measured fresh right before
                # the joiner connects rather than derived from this
                # threshold -- but the MARGIN between "positioned through
                # chunk_timestamps" and "fell back to the oldest available
                # chunk" scales with how much has accumulated by the time
                # the fallback would apply. At one window's worth of
                # accumulation the fallback's "oldest available" chunk sits
                # close enough to where correct positioning would also land
                # that the two are barely distinguishable; three widens that
                # gap comfortably past the margin below.
                wait_until(
                    lambda: self.status(channel)[1].get("buffer_index", 0)
                    >= 3 * chunks_for_the_window,
                    timeout=10,
                    what="three times the behind-live window to accumulate in the ring buffer",
                )

                # The current write head, in packets, estimated from
                # `buffer_index` (chunks WRITTEN) rather than from `first`'s
                # own read position: `first` has not read anything since its
                # initial 4 packets, so its stream position is stale, but
                # production never stops, so a status call taken right
                # before the joiner connects is the freshest reference this
                # test can get.
                _, status_before_joiner = self.status(channel)
                live_index_estimate = status_before_joiner["buffer_index"] * packets_per_chunk

                _, joiner = open_tune(self, channel)
                joiner_first_packet = joiner.read(TS_PACKET_SIZE)
                assert_ts_aligned(joiner_first_packet)
                joiner_start_index = packet_index(joiner_first_packet)

            backlog_packets = live_index_estimate - joiner_start_index
            # Two chunks' margin: `chunks_for_the_window` truncates towards
            # zero (a real quantization, not slack added for comfort), and
            # `live_index_estimate` is a moment old by the time the joiner
            # actually connects. Both broken mechanisms miss by far more
            # than this margin can absorb: live-head positioning gives a
            # backlog near zero; the oldest-available fallback gives one
            # near the whole accumulated buffer, many times the window.
            self.assertAlmostEqual(
                backlog_packets, packets_for_the_window, delta=2 * packets_per_chunk
            )
            self.stop_channel(channel)
