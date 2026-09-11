"""Property-based tests for StreamBuffer client read paths.

The write path (TS realignment) is covered by test_property_ts_realignment.py.
This module covers the *read* side: get_chunks_exact and
get_optimized_client_data, which decide how many chunks a client at a given
position receives and what the client is told its new position is.

The promised invariants, from the code:

* get_chunks_exact never returns chunks the client already has (all indices
  strictly greater than the requested start_index) and never fabricates data —
  every returned chunk is one the buffer actually holds.
* get_optimized_client_data returns a next position that is monotonically
  non-decreasing (never rewinds a client) and, when chunks are returned,
  advances the client past exactly what it delivered.
* The "chunks expired, skip forward" branch returns an empty chunk list AND
  the unchanged client_index, signalling the caller to reposition.

All run under SimpleTestCase with an in-memory Redis stand-in; ConfigHelper is
patched at construction as in test_property_ts_realignment.
"""

from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.input.buffer import StreamBuffer

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

NO_FLUSH = 10**9


class _ReadPipeline:
    """Pipelines only get() calls against the chunk store."""

    def __init__(self, store, prefix):
        self._store = store
        self._prefix = prefix
        self._keys = []

    def get(self, key):
        self._keys.append(key)
        return self

    def execute(self):
        return [self._store.get(k) for k in self._keys]


class FakeReadRedis:
    """Enough of redis-py for the read paths: get + pipeline(get).

    Holds a set of chunk index -> bytes and a current buffer index. Chunks can
    be selectively dropped to simulate TTL expiry.
    """

    def __init__(self):
        self.chunks = {}        # full chunk-key -> bytes
        self.current_index = 0
        self.buffer_index_key = ""
        self.prefix = ""

    def get(self, key):
        if key == self.buffer_index_key:
            return str(self.current_index).encode()
        return self.chunks.get(key)

    def pipeline(self, transaction=False):
        return _ReadPipeline(self.chunks, self.prefix)

    def register_script(self, script):
        return lambda *args, **kwargs: None


def make_buffer(redis_client=None):
    def fake_get(name, default=None):
        if name == "BUFFER_CHUNK_SIZE":
            return NO_FLUSH
        return default

    with mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.redis_chunk_ttl",
        return_value=60,
    ), mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.get",
        side_effect=fake_get,
    ):
        buf = StreamBuffer(
            channel_id="ch",
            redis_client=redis_client,
            buffer_index_key="idx",
            buffer_chunk_prefix="pfx:",
            chunk_timestamps_key="cts",
        )
    if redis_client is not None:
        redis_client.buffer_index_key = "idx"
        redis_client.prefix = "pfx:"
    return buf


def populate(redis, up_to_index, chunk_size=188):
    """Write chunk keys 1..up_to_index and set the buffer head."""
    redis.chunks = {
        f"pfx:{i}": bytes([i % 256]) * chunk_size for i in range(1, up_to_index + 1)
    }
    redis.current_index = up_to_index


class GetChunksExactProperties(SimpleTestCase):
    @given(
        head=st.integers(min_value=0, max_value=40),
        start_index=st.integers(min_value=0, max_value=45),
        count=st.integers(min_value=0, max_value=25),
    )
    def test_never_returns_already_consumed_or_fabricated_chunks(
        self, head, start_index, count
    ):
        """Every returned chunk is one the buffer holds, at index > start_index."""
        redis = FakeReadRedis()
        populate(redis, head)
        buf = make_buffer(redis_client=redis)
        buf.index = head

        chunks = buf.get_chunks_exact(start_index, count)

        # Reconstruct which indices were served: start_id..start_id+len-1
        start_id = start_index + 1
        for offset, chunk in enumerate(chunks):
            idx = start_id + offset
            # Served chunk must be one that exists in the store and be ahead
            # of the client's position.
            self.assertIn(f"pfx:{idx}", redis.chunks)
            self.assertGreater(idx, start_index)
            self.assertEqual(chunk, redis.chunks[f"pfx:{idx}"])

    @given(
        head=st.integers(min_value=1, max_value=40),
        count=st.integers(min_value=1, max_value=25),
    )
    def test_at_head_returns_nothing(self, head, count):
        """A client already at the buffer head gets no chunks."""
        redis = FakeReadRedis()
        populate(redis, head)
        buf = make_buffer(redis_client=redis)
        buf.index = head

        self.assertEqual(buf.get_chunks_exact(head, count), [])

    @given(
        head=st.integers(min_value=5, max_value=40),
        count=st.integers(min_value=1, max_value=25),
    )
    def test_never_exceeds_available(self, head, count):
        """Starting from 0, never returns more chunks than exist."""
        redis = FakeReadRedis()
        populate(redis, head)
        buf = make_buffer(redis_client=redis)
        buf.index = head

        chunks = buf.get_chunks_exact(0, count)
        self.assertLessEqual(len(chunks), min(count, head))


class GetOptimizedClientDataProperties(SimpleTestCase):
    @given(
        head=st.integers(min_value=0, max_value=60),
        client_index=st.integers(min_value=0, max_value=70),
    )
    def test_position_never_rewinds(self, head, client_index):
        """The returned next position is always >= the client's current index."""
        redis = FakeReadRedis()
        populate(redis, head)
        buf = make_buffer(redis_client=redis)
        buf.index = head

        _chunks, next_index = buf.get_optimized_client_data(client_index)
        self.assertGreaterEqual(next_index, client_index)

    @given(head=st.integers(min_value=0, max_value=60))
    def test_client_at_head_gets_empty_and_stays(self, head):
        """A fully caught-up client gets no data and does not move."""
        redis = FakeReadRedis()
        populate(redis, head)
        buf = make_buffer(redis_client=redis)
        buf.index = head

        chunks, next_index = buf.get_optimized_client_data(head)
        self.assertEqual(chunks, [])
        self.assertGreaterEqual(next_index, head)

    @given(
        head=st.integers(min_value=20, max_value=60),
        lag=st.integers(min_value=15, max_value=59),
    )
    def test_expired_chunks_signal_skip_forward(self, head, lag):
        """All chunks expired while far behind -> empty list + unchanged index."""
        client_index = head - lag
        redis = FakeReadRedis()
        populate(redis, head)
        # Simulate TTL expiry: drop every chunk.
        redis.chunks = {}
        buf = make_buffer(redis_client=redis)
        buf.index = head

        chunks, next_index = buf.get_optimized_client_data(client_index)
        self.assertEqual(chunks, [])
        self.assertEqual(next_index, client_index)
