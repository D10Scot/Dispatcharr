"""Property-based tests for find_ts_sync (apps/proxy/utils.py).

find_ts_sync scans the first bytes of an upstream HTTP response for a valid
MPEG-TS sync chain: three consecutive 0x47 sync bytes exactly TS_PACKET_SIZE
(188) apart. Callers (timeshift catch-up, VOD range probes) use the offset to
strip a PHP/HTML error preamble before streaming, and treat -1 as "not TS".
The properties state exactly what the implementation promises:

* the result is always -1 or an offset that genuinely starts a three-packet
  sync chain (no false positives, verified against the buffer itself);
* the function is total — arbitrary bytes, including buffers full of 0x47,
  never raise and always return int;
* minimality: the returned offset is the *first* chain start (nothing earlier
  in the buffer satisfies the predicate);
* any planted chain at a searched position is found, and the offset is
  independent of bytes after the chain and before the insertion point
  (provided the prefix itself contains no chain);
* buffers too short to contain a full chain always return -1.

Runs without Redis or the database (SimpleTestCase, pure function).
"""

import random

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.utils import _TS_PACKET_SIZE, _TS_SYNC_BYTE, find_ts_sync

# CI-deterministic profile. Registered/loaded at module import because the
# Django test runner has no pytest-style conftest hook. derandomize=True makes
# runs reproducible; deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

PKT = _TS_PACKET_SIZE
SYNC = _TS_SYNC_BYTE


def _starts_chain(buf, i):
    """Independent restatement of the chain predicate find_ts_sync searches."""
    return (
        0 <= i
        and i + 2 * PKT < len(buf)
        and buf[i] == SYNC
        and buf[i + PKT] == SYNC
        and buf[i + 2 * PKT] == SYNC
    )


# Byte distributions that matter: biased toward the sync byte (dense 0x47
# fields are where false positives and missed chains would hide), plus fully
# arbitrary bytes. st.binary has no alphabet parameter, so build biased
# buffers from a sampled alphabet directly.
def _biased_buffer():
    return st.lists(
        st.sampled_from([SYNC, SYNC, SYNC, 0x00, 0xFF, 0x11, 0x47 ^ 0xFF]),
        min_size=0,
        max_size=3 * PKT + 64,
    ).map(bytes)


arbitrary_buffers = st.binary(min_size=0, max_size=3 * PKT + 64) | _biased_buffer()


class FindTsSyncProperties(SimpleTestCase):
    @given(buf=arbitrary_buffers)
    def test_result_is_minus_one_or_a_real_chain_start(self, buf):
        """No false positives: a non-negative result starts a valid chain."""
        result = find_ts_sync(buf)
        self.assertIsInstance(result, int)
        if result != -1:
            self.assertTrue(
                _starts_chain(buf, result),
                f"returned {result} but buffer does not start a chain there",
            )

    @given(buf=arbitrary_buffers)
    def test_result_is_the_first_chain_start(self, buf):
        """Minimality: no chain starts at any offset before the result."""
        result = find_ts_sync(buf)
        if result == -1:
            self.assertFalse(
                any(_starts_chain(buf, i) for i in range(len(buf))),
                "returned -1 although a chain exists",
            )
        else:
            self.assertFalse(
                any(_starts_chain(buf, i) for i in range(result)),
                f"chain exists before returned offset {result}",
            )

    @given(buf=st.binary(min_size=0, max_size=2 * PKT))
    def test_short_buffers_never_match(self, buf):
        """Fewer than 2*PKT+1 bytes cannot contain a full chain."""
        self.assertEqual(find_ts_sync(buf), -1)

    @given(
        prefix_len=st.integers(min_value=0, max_value=128),
        suffix_len=st.integers(min_value=0, max_value=64),
        seed=st.integers(min_value=0, max_value=2**31 - 1),
    )
    def test_planted_chain_is_found(self, prefix_len, suffix_len, seed):
        """A chain planted after a chain-free prefix is found at the prefix
        length, regardless of the packet payloads or trailing bytes."""
        rng = random.Random(seed)
        # 0x00 prefix is guaranteed chain-free (no 0x47 bytes at all).
        prefix = bytes(prefix_len)
        chain = bytes([SYNC]) + bytes(rng.randrange(256) for _ in range(PKT - 1))
        buf = prefix + chain * 3 + bytes(
            rng.randrange(256) for _ in range(suffix_len)
        )
        self.assertEqual(find_ts_sync(buf), prefix_len)

    @given(
        offset=st.integers(min_value=0, max_value=64),
        seed=st.integers(min_value=0, max_value=2**31 - 1),
    )
    def test_trailing_bytes_do_not_change_result(self, offset, seed):
        """Bytes after the chain are irrelevant: appending an arbitrary tail
        to a buffer that ends exactly at the third sync byte must not change
        the reported offset."""
        rng = random.Random(seed)
        # 0x00 prefix is guaranteed chain-free (no 0x47 bytes at all).
        head = bytes(offset) + (bytes([SYNC]) + bytes(PKT - 1)) * 3
        tail = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
        self.assertEqual(find_ts_sync(head), find_ts_sync(head + tail))
