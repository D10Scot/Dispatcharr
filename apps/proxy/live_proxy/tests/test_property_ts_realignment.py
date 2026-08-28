"""Property-based tests for StreamBuffer TS packet realignment.

`StreamBuffer.add_chunk` (apps/proxy/live_proxy/input/buffer.py) realigns an
arbitrary byte stream to 188-byte MPEG-TS packet boundaries: incoming bytes are
combined with the carried partial packet, cut at the largest multiple of
TS_PACKET_SIZE, and the remainder is carried forward. The realignment is purely
length-based — the implementation deliberately does not inspect the 0x47 sync
byte — so the properties below state exactly what the code promises and no more:

* the staged write buffer always holds a whole number of 188-byte packets and
  the carried partial packet is always shorter than one packet;
* no input bytes are fabricated, dropped, or reordered (flushed chunks + write
  buffer + partial packet reproduce the input stream exactly);
* how the same byte stream is split into chunks does not affect the result;
* chunks flushed to storage are exactly ``target_chunk_size`` bytes and are
  indexed contiguously and monotonically;
* ``reset_buffer_position`` clears all staged state.

These tests run without Redis or the database: the buffer is built with a
minimal in-memory Redis stand-in (or none at all), and ConfigHelper is patched
so construction never reaches CoreSettings.
"""

from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer

# CI-deterministic profile. Registered/loaded at module import because the
# Django test runner has no pytest-style conftest hook. derandomize=True makes
# runs reproducible; deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Large enough that the Redis-flush path never triggers in the in-memory tests.
NO_FLUSH = 10**9


class FakePipeline:
    """Just enough of redis-py's pipeline for StreamBuffer's write path."""

    def __init__(self, store):
        self._store = store
        self._pending = []

    def setex(self, key, ttl, value):
        self._pending.append((key, value))
        return self

    def zadd(self, *args, **kwargs):
        return self

    def zremrangebyscore(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    def execute(self):
        for key, value in self._pending:
            self._store[key] = value
        self._pending = []
        return []


class FakeRedis:
    """Minimal in-memory stand-in for the calls StreamBuffer makes."""

    def __init__(self):
        self.chunks = {}
        self.counter = 0

    def get(self, key):
        return None

    def incr(self, key):
        self.counter += 1
        return self.counter

    def register_script(self, script):
        return lambda *args, **kwargs: None

    def pipeline(self, transaction=False):
        return FakePipeline(self.chunks)


def make_buffer(target_chunk_size=NO_FLUSH, redis_client=None):
    """Build a StreamBuffer without touching the database.

    ConfigHelper.redis_chunk_ttl()/get() reach TSConfig.get_proxy_settings()
    which reads CoreSettings — forbidden under SimpleTestCase — so both are
    patched for the duration of construction.
    """

    def fake_get(name, default=None):
        if name == "BUFFER_CHUNK_SIZE":
            return target_chunk_size
        return default

    with mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.redis_chunk_ttl",
        return_value=60,
    ), mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.get",
        side_effect=fake_get,
    ):
        return StreamBuffer(channel_id=None, redis_client=redis_client)


def partial_bytes(buf):
    """The carried partial packet — created lazily on first add_chunk."""
    return bytes(getattr(buf, "_partial_packet", b""))


# A stream of arbitrary chunks, sized so several packets' worth of data (and
# plenty of ragged edges) flow through, while staying far below NO_FLUSH.
chunk_lists = st.lists(
    st.binary(min_size=0, max_size=3 * TS_PACKET_SIZE + 17), max_size=20
)


@st.composite
def data_and_cut_points(draw):
    """A byte stream plus an arbitrary way of splitting it into pieces."""
    data = draw(st.binary(max_size=6 * TS_PACKET_SIZE))
    cuts = draw(
        st.lists(st.integers(min_value=0, max_value=len(data)), max_size=8)
    )
    bounds = sorted([0, *cuts, len(data)])
    pieces = [data[a:b] for a, b in zip(bounds, bounds[1:])]
    return data, pieces


class TsRealignmentProperties(SimpleTestCase):
    @given(chunks=chunk_lists)
    def test_staged_state_is_packet_aligned(self, chunks):
        """Write buffer holds whole packets; partial carry is < one packet."""
        buf = make_buffer()
        for chunk in chunks:
            result = buf.add_chunk(chunk)
            # Non-empty input is accepted; empty input is rejected.
            self.assertEqual(result, bool(chunk))
            self.assertEqual(len(buf._write_buffer) % TS_PACKET_SIZE, 0)
            self.assertLess(len(partial_bytes(buf)), TS_PACKET_SIZE)

    @given(chunks=chunk_lists)
    def test_no_bytes_fabricated_or_dropped(self, chunks):
        """Below the flush threshold, staged state reproduces the input exactly."""
        buf = make_buffer()
        for chunk in chunks:
            buf.add_chunk(chunk)
        staged = bytes(buf._write_buffer) + partial_bytes(buf)
        self.assertEqual(staged, b"".join(chunks))

    @given(payload=data_and_cut_points())
    def test_rechunking_does_not_change_result(self, payload):
        """Arbitrary chunk boundaries yield identical realigned state."""
        data, pieces = payload
        whole = make_buffer()
        whole.add_chunk(data)
        split = make_buffer()
        for piece in pieces:
            split.add_chunk(piece)
        self.assertEqual(bytes(whole._write_buffer), bytes(split._write_buffer))
        self.assertEqual(partial_bytes(whole), partial_bytes(split))

    @given(chunks=chunk_lists, packets_per_chunk=st.integers(1, 4))
    def test_flushed_chunks_conserve_the_stream(self, chunks, packets_per_chunk):
        """Flushed chunks are exactly target-sized, contiguously indexed, and
        together with the staged remainder reproduce the input stream."""
        target = packets_per_chunk * TS_PACKET_SIZE
        redis = FakeRedis()
        buf = make_buffer(target_chunk_size=target, redis_client=redis)
        for chunk in chunks:
            buf.add_chunk(chunk)

        flushed = [
            redis.chunks[f"{buf.buffer_prefix}{i}"]
            for i in range(1, redis.counter + 1)
        ]
        for chunk_data in flushed:
            self.assertEqual(len(chunk_data), target)
        self.assertEqual(buf.index, redis.counter)

        reassembled = (
            b"".join(flushed) + bytes(buf._write_buffer) + partial_bytes(buf)
        )
        self.assertEqual(reassembled, b"".join(chunks))

    @given(chunks=chunk_lists)
    def test_stopping_and_empty_input_change_nothing(self, chunks):
        buf = make_buffer()
        for chunk in chunks:
            buf.add_chunk(chunk)
        staged = bytes(buf._write_buffer) + partial_bytes(buf)

        self.assertFalse(buf.add_chunk(b""))
        self.assertFalse(buf.add_chunk(None))
        buf.stopping = True
        self.assertFalse(buf.add_chunk(b"\x47" + b"\x00" * (TS_PACKET_SIZE - 1)))

        self.assertEqual(bytes(buf._write_buffer) + partial_bytes(buf), staged)

    @given(chunks=chunk_lists)
    def test_reset_clears_all_staged_state(self, chunks):
        buf = make_buffer()
        for chunk in chunks:
            buf.add_chunk(chunk)
        buf.reset_buffer_position()
        self.assertEqual(len(buf._write_buffer), 0)
        self.assertEqual(len(partial_bytes(buf)), 0)
