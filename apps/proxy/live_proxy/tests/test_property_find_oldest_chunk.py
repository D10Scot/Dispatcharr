"""Property-based tests for StreamBuffer.find_oldest_available_chunk.

The Lua binary search in apps/proxy/live_proxy/input/buffer.py scans the chunk
keyspace [client_index+1 .. buffer head] for the lowest-index chunk that still
exists in Redis. Chunks all share one TTL and are written sequentially, so the
alive set is a *contiguous suffix* of the index range — that is the invariant
the search relies on, and the properties below state exactly it:

* on any contiguous-suffix alive set the result equals the linear-scan answer
  (the smallest alive index, or None when the range is empty);
* a result never points at a dead chunk, and is always the smallest alive one;
* when the buffer head itself is dead the answer is None, whatever else lives.

The search runs against a fake Redis whose registered-script shim evaluates the
documented algorithm over a set of "existing" chunk keys, so these tests pin
the algorithm, not a Python re-implementation's divergent behaviour.

Runs without Redis or the database (SimpleTestCase; ConfigHelper patched).
"""

from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.input.buffer import StreamBuffer

# CI-deterministic profile — see test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class BinarySearchRedis:
    """Fake Redis whose register_script returns the documented binary search.

    Mirrors _FIND_OLDEST_CHUNK_LUA: -1 when the head key is missing, otherwise
    binary-search [low, high] for the smallest existing index. The fake exists
    so the *search algorithm* is exercised against arbitrary existence patterns;
    the invariant under test is that this algorithm agrees with linear scan
    exactly when the alive set is a contiguous suffix.
    """

    def __init__(self, existing):
        self.existing = set(existing)

    def get(self, key):
        return None

    def register_script(self, script):
        def run(keys=None, args=None):
            prefix, low, high = args[0], int(args[1]), int(args[2])

            def exists(i):
                return f"{prefix}{i}" in self.existing

            if not exists(high):
                return -1
            result = high
            while low <= high:
                mid = (low + high) // 2
                if exists(mid):
                    result = mid
                    high = mid - 1
                else:
                    low = mid + 1
            return result

        return run

    # Calls the buffer may make but this path never reaches.
    def pipeline(self, transaction=False):  # pragma: no cover
        raise NotImplementedError

    def incr(self, key):  # pragma: no cover
        raise NotImplementedError


def make_buffer(existing, head_index):
    """Build a StreamBuffer positioned at head_index over the fake keyspace."""
    redis = BinarySearchRedis(existing)
    with mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.redis_chunk_ttl",
        return_value=60,
    ), mock.patch(
        "apps.proxy.live_proxy.input.buffer.ConfigHelper.get",
        side_effect=lambda name, default=None: default,
    ):
        buf = StreamBuffer(
            channel_id="prop",
            redis_client=redis,
            buffer_chunk_prefix="prop:chunk:",
        )
    buf.index = head_index
    return buf


@st.composite
def suffix_alive_sets(draw):
    """Head index plus a contiguous-suffix alive set ending at the head."""
    head = draw(st.integers(min_value=1, max_value=500))
    # oldest_alive in [1, head+1]; head+1 means the alive set is empty.
    oldest_alive = draw(st.integers(min_value=1, max_value=head + 1))
    existing = {f"prop:chunk:{i}" for i in range(oldest_alive, head + 1)}
    return head, existing


class FindOldestChunkProperties(SimpleTestCase):
    @given(payload=suffix_alive_sets(), client_index=st.integers(min_value=0, max_value=500))
    def test_matches_linear_scan_on_contiguous_suffix(self, payload, client_index):
        """On the invariant the code assumes, binary search == linear scan."""
        head, existing = payload
        buf = make_buffer(existing, head)
        result = buf.find_oldest_available_chunk(client_index)

        alive_in_range = [
            i
            for i in range(client_index + 1, head + 1)
            if f"prop:chunk:{i}" in existing
        ]
        if not alive_in_range:
            self.assertIsNone(result)
        else:
            self.assertEqual(result, min(alive_in_range) - 1)

    @given(payload=suffix_alive_sets(), client_index=st.integers(min_value=0, max_value=500))
    def test_result_never_points_at_dead_chunk(self, payload, client_index):
        """The first chunk the client will read (result+1) must exist."""
        head, existing = payload
        buf = make_buffer(existing, head)
        result = buf.find_oldest_available_chunk(client_index)
        if result is not None:
            self.assertIn(f"prop:chunk:{result + 1}", existing)
            # And it must be the *smallest* alive index at or after client_index+1.
            for i in range(client_index + 1, result + 1):
                self.assertNotIn(f"prop:chunk:{i}", existing)

    @given(head=st.integers(min_value=1, max_value=500), client_index=st.integers(min_value=0, max_value=500))
    def test_dead_head_means_no_position(self, head, client_index):
        """Head chunk expired => None, however many older chunks survive."""
        existing = {
            f"prop:chunk:{i}" for i in range(1, head)  # everything except head
        }
        buf = make_buffer(existing, head)
        self.assertIsNone(buf.find_oldest_available_chunk(client_index))

    @given(client_index=st.integers(min_value=0, max_value=500))
    def test_empty_keyspace_returns_none(self, client_index):
        buf = make_buffer(set(), head_index=10)
        self.assertIsNone(buf.find_oldest_available_chunk(client_index))

    def test_client_at_head_returns_none(self):
        """Nothing newer than the client exists."""
        existing = {f"prop:chunk:{i}" for i in range(1, 11)}
        buf = make_buffer(existing, head_index=10)
        self.assertIsNone(buf.find_oldest_available_chunk(10))
