"""What a client actually receives from the relay, and what the client set does.

Matrix rows 9, 10 and 13 (docs/relay-parity-matrix.md). Every assertion here is
about something a client or an admin can observe over HTTP -- delivered bytes,
a status field, a response status -- because that is what ports to a Go test
row-for-row (spec section "The subprocess harness", the composition rule).
"""

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase

# The PID synthetic_ts() writes by default (harness/asset.py:21).
SOURCE_PID = 0x100


def continuity_counters(data):
    """The 4-bit continuity counter of every 188-byte packet in `data`.

    Byte 3's low nibble, per the TS header synthetic_ts() builds
    (harness/asset.py:40: `0x10 | (i % 16)`).
    """
    return [data[offset + 3] & 0x0F for offset in range(0, len(data), TS_PACKET_SIZE)]


class PacketStreamTests(RelayHarnessTestCase):
    def test_the_delivered_stream_is_whole_packets_in_unbroken_order(self):
        """Matrix row 9: realignment to 188-byte boundaries, partials carried forward.

        The relay never sees the upstream's writes as packets. The stand-in
        copies its input in 8,192-byte reads (harness/standin.py:45) and 8,192
        is not a multiple of 188, so StreamBuffer.add_chunk is genuinely handed
        buffers that end mid-packet and genuinely has to carry the remainder
        (input/buffer.py:79-91). If it dropped or duplicated the remainder, the
        continuity-counter chain below would break at a chunk boundary -- which
        is exactly what a client's decoder would see.
        """
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            body = self.tune(channel, read_bytes=400 * TS_PACKET_SIZE)
            self.stop_channel(channel)

        assert_ts_aligned(body)
        counters = continuity_counters(body)
        breaks = [
            index
            for index in range(1, len(counters))
            if counters[index] != (counters[index - 1] + 1) % 16
        ]
        self.assertEqual(breaks, [], "continuity counters must advance by 1 mod 16")
