"""A running channel switched to another source, and a client that joins late.

Matrix rows 7 and 8. Both drive ChannelService's switch path and the TS
generator's client-positioning path through the admin HTTP surface -- which is
what makes them portable: the Go relay serves the same two routes.
"""

from .harness.asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
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
# numbered_ts()'s base pid, and how many packets it lays down. Comfortably
# above any packet count PositioningTests produces within its own budget (a
# couple of seconds at NOMINAL_BYTE_RATE's pacing, comfortably under 3,000
# packets even with generous margin), so the payload the fake upstream loops
# never wraps back to POSITION_BASE_PID mid-test -- see numbered_ts()'s
# docstring for why that would make a packet's pid ambiguous with an
# earlier one.
POSITION_BASE_PID = 0x100
POSITION_PACKETS = 6000


def pids(data):
    """Every distinct PID in `data`, read from the 13 bits after the sync byte."""
    return {
        ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
        for offset in range(0, len(data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE)
    }


def numbered_ts(packets: int = POSITION_PACKETS, base_pid: int = POSITION_BASE_PID) -> bytes:
    """`packets` TS packets whose pid directly encodes the packet's position.

    synthetic_ts()'s payload (harness/asset.py) is a function of `i % 256`
    (every payload byte is `(i + j) % 256`) and so are packets `i` and
    `i + 256` byte-for-byte identical -- fine for row 9's continuity check,
    which only needs adjacent packets to differ, but useless for "how far
    behind is this packet", which needs an unambiguous answer over a window
    that can exceed 256 packets. See harness/README.md's "the unpaced
    upstream" note for the companion trap this asset avoids on the timing
    side. Here pid = base_pid + i instead: unique across the whole payload
    (checked against the 13-bit pid space below), so a packet's pid IS its
    position -- no periodicity, and (unlike elapsed read time in this
    harness) nothing a fast, unthrottled read can hide.
    """
    if packets < 1:
        raise ValueError("packets must be >= 1")
    if base_pid + packets - 1 > 0x1FFF:
        raise ValueError("base_pid + packets exceeds the 13-bit pid space")
    out = bytearray()
    for i in range(packets):
        pid = base_pid + i
        out.append(TS_SYNC_BYTE)
        out.append((pid >> 8) & 0x1F)
        out.append(pid & 0xFF)
        out.append(0x10 | (i % 16))
        out.extend(bytes((i + j) % 256 for j in range(TS_PACKET_SIZE - 4)))
    return bytes(out)


def packet_pid(packet: bytes) -> int:
    """The pid of a single TS_PACKET_SIZE-byte packet, per numbered_ts()."""
    return ((packet[1] & 0x1F) << 8) | packet[2]


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

        Row 8's claim is WHAT a joining client receives first, not how fast:
        a client positioned `new_client_behind_seconds` back is served
        content the already-connected client saw earlier, not whatever was
        just produced. Two traps rule out the obvious assertions:

        Elapsed read time cannot show this in this harness. Reads here are
        never throttled to production pacing (see harness/README.md, "the
        unpaced upstream"): a positioned-behind client and a
        positioned-at-head client both drain any requested amount
        near-instantly, because the fake upstream races ahead of any client
        and writes chunks to Redis long before they are asked for. An
        earlier version of this test asserted on elapsed time and passed
        against a genuinely broken positioning mechanism -- see the retracted
        step in the 2a-3 plan for the measurements.

        "This content appeared somewhere earlier" is not enough either.
        synthetic_ts()'s payload repeats every 256 packets, so the newest
        packet is byte-identical to one already seen 256 packets ago --
        content PRESENCE proves nothing about position. numbered_ts() gives
        every packet a unique pid instead, so position is read directly off
        the wire, the same way a client would encounter it.
        """
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        # The row says "roughly 5 seconds behind live", so pin the default
        # before compressing it -- otherwise nothing in this suite asserts the 5.
        TSConfig.clear_proxy_settings_cache()
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), 5)
        self.set_proxy_setting(new_client_behind_seconds=BEHIND_SECONDS)
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), BEHIND_SECONDS)

        bytes_per_second = NOMINAL_BYTE_RATE  # the numbered upstream's own rate is 1.0
        chunks_for_the_window = int(
            BEHIND_SECONDS * bytes_per_second // TSConfig.BUFFER_CHUNK_SIZE
        )
        packets_per_chunk = TSConfig.BUFFER_CHUNK_SIZE // TS_PACKET_SIZE
        packets_for_the_window = chunks_for_the_window * packets_per_chunk

        numbered = FakeUpstream(payload=numbered_ts()).start()
        self.addCleanup(numbered.stop)

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=numbered.url, profile=profile)
            with self.tuned(channel) as first:
                first.read(4 * TS_PACKET_SIZE)
                # Some real backlog to work with -- not load-bearing on its
                # own, since the catch-up read below re-measures the buffer
                # right before draining it rather than trusting this number.
                wait_until(
                    lambda: self.status(channel)[1].get("buffer_index", 0)
                    >= chunks_for_the_window,
                    timeout=10,
                    what="the behind-live window to accumulate in the ring buffer",
                )

                # Catch `first` up to (almost) the current write head, measured
                # NOW rather than reusing the wait_until threshold above:
                # production never stops, so by the time this read would
                # start, more exists than the threshold alone guarantees.
                # Reading everything already produced -- known, not
                # estimated, from this fresh status call -- keeps
                # `last_pid_first_saw` as close to "the live head a moment
                # ago" as this test can get, which is what makes the
                # comparison below meaningful rather than comparing the
                # joiner against a stale snapshot.
                _, status_before_catchup = self.status(channel)
                produced_packets = status_before_catchup["buffer_index"] * packets_per_chunk
                # 10-packet margin: `buffer_index` counts chunks WRITTEN to
                # Redis, and the bytes for the newest one may not have
                # finished arriving over this HTTP connection yet.
                catchup_packets = produced_packets - 4 - 10
                caught_up = first.read(catchup_packets * TS_PACKET_SIZE)
                assert_ts_aligned(caught_up)
                last_pid_first_saw = packet_pid(caught_up[-TS_PACKET_SIZE:])

                _, joiner = open_tune(self, channel)
                joiner_first_packet = joiner.read(TS_PACKET_SIZE)
                assert_ts_aligned(joiner_first_packet)
                joiner_first_pid = packet_pid(joiner_first_packet)

            # Only the HTTP round trip for open_tune() and one more read
            # separate `last_pid_first_saw` from the joiner's own connect
            # moment, so the margin only needs to absorb that gap -- half
            # the window is generous against it while still requiring a
            # real, substantial distance: a near-head start (the broken
            # mechanism) cannot pass by accident.
            self.assertLess(
                joiner_first_pid,
                last_pid_first_saw - (packets_for_the_window // 2),
            )
            self.stop_channel(channel)
