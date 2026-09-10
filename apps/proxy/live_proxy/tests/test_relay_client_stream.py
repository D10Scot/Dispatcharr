"""What a client actually receives from the relay, and what the client set does.

Matrix rows 9, 10 and 13 (docs/relay-parity-matrix.md). Every assertion here is
about something a client or an admin can observe over HTTP -- delivered bytes,
a status field, a response status -- because that is what ports to a Go test
row-for-row (spec section "The subprocess harness", the composition rule).
"""

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.control import ControlMixin, nginx_headers, open_tune
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until

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


class ClientSetTests(ControlMixin, RelayHarnessTestCase):
    def test_the_client_set_from_three_sharing_clients_to_an_empty_channel(self):
        """Matrix row 10, and row 13's registration half.

        One narrative because it is one channel's client set, and because each
        step needs the previous one's state: three clients on one upstream, a
        fourth request reusing a registered client id, one client stopped by the
        operator, then the whole channel stopped. The upstream's request_count
        is the load-bearing observation -- it is 1 at the start and still 1 at
        the end, so nothing along the way opened a second provider connection.
        """
        client_id = "harness-doomed-client"
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            # The first client takes a chosen id (so the operator can name it
            # below); the other two get relay-minted ones.
            readers = []
            for headers in (nginx_headers(channel, client_id), None, None):
                _, reader = open_tune(self, channel, headers=headers)
                reader.read(4 * TS_PACKET_SIZE)
                readers.append(reader)

            _, info = self.status(channel)
            self.assertEqual(self.upstream.request_count, 1)
            self.assertEqual(info["client_count"], 3)

            # Row 13, registration: add_client() refuses a client id it has
            # already seen (client_manager.py:215-221) and stream_ts turns that
            # into a 503 rather than a second registration (views.py:712-722).
            duplicate, _ = open_tune(
                self, channel, headers=nginx_headers(channel, client_id), expect_status=503
            )
            self.assertEqual(duplicate.json(), {"error": "Failed to register client"})
            self.assertEqual(self.status(channel)[1]["client_count"], 3)

            # ChannelService.stop_client: the named client's stream ends, the
            # other two keep receiving.
            response = self.stop_client(channel, client_id)
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.json()["locally_processed"], True)
            with self.assertRaises(AssertionError):
                readers[0].read(4000 * TS_PACKET_SIZE)
            readers[1].read(4 * TS_PACKET_SIZE)
            readers[2].read(4 * TS_PACKET_SIZE)
            wait_until(
                lambda: self.status(channel)[1]["client_count"] == 2,
                timeout=10,
                what="the stopped client to leave the channel's client list",
            )

            # ChannelService.stop_channel: every remaining stream ends, and the
            # upstream was never reconnected.
            response = self.stop_channel_over_http(channel)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["previous_state"], {"state": "active"})
            for reader in readers[1:]:
                with self.assertRaises(AssertionError):
                    reader.read(4000 * TS_PACKET_SIZE)
            self.assertEqual(self.upstream.request_count, 1)
