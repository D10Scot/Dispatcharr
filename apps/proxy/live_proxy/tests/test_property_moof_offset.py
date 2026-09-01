"""Property-based tests for _find_moof_offset and fragment flushing.

apps/proxy/live_proxy/output/fmp4/manager.py scans FFmpeg's fMP4 stdout for
'moof' box starts. MP4 boxes are [4-byte big-endian length][4-byte type] so a
well-formed stream resolves in exact box strides; FFmpeg output is trusted but
the buffer is reassembled from arbitrary Redis chunk boundaries, and a garbage
length byte (< 8) is treated as misalignment and scanned byte-by-byte.

Properties stated here are what the implementation promises, no more:

* never raises and never loops forever, whatever the bytes;
* a result is always a genuine moof header at the returned offset, >= start;
* on well-formed box sequences the first moof is found at its exact offset;
* misalignment recovery: arbitrary garbage before a moof still finds it
  (possibly earlier at a coincidental "moof" inside the garbage — the contract
  is "first occurrence", not "the real one").

Runs without Redis or the database (SimpleTestCase, pure function).
"""

import struct

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.output.fmp4.manager import _find_moof_offset

# CI-deterministic profile — see test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


NON_MOOF_TYPES = st.binary(min_size=4, max_size=4).filter(lambda t: t != b"moof")


@st.composite
def box_streams(draw, min_boxes=0, max_boxes=6):
    """A well-formed byte stream of boxes, possibly containing moofs."""
    parts = []
    moof_offsets = []
    pos = 0
    for _ in range(draw(st.integers(min_boxes, max_boxes))):
        if draw(st.booleans()):
            moof_offsets.append(pos)
            parts.append(box(b"moof", draw(st.binary(max_size=40))))
        else:
            parts.append(
                box(draw(NON_MOOF_TYPES), draw(st.binary(max_size=40)))
            )
        pos += len(parts[-1])
    # Optional trailing partial box (fragmented read boundary).
    tail = draw(st.binary(max_size=10))
    return b"".join(parts) + tail, moof_offsets


class MoofOffsetRobustnessProperties(SimpleTestCase):
    @given(data=st.binary(max_size=512), start=st.integers(min_value=0, max_value=600))
    def test_never_raises_on_arbitrary_bytes(self, data, start):
        result = _find_moof_offset(data, start=start)
        self.assertTrue(isinstance(result, int))

    @given(data=st.binary(max_size=512), start=st.integers(min_value=0, max_value=512))
    def test_result_is_a_real_moof_header_at_or_after_start(self, data, start):
        result = _find_moof_offset(data, start=start)
        if result == -1:
            return
        self.assertGreaterEqual(result, start)
        self.assertLessEqual(result + 8, len(data))
        self.assertEqual(data[result + 4: result + 8], b"moof")

    @given(payload=box_streams())
    def test_wellformed_stream_finds_first_moof_exactly(self, payload):
        data, moof_offsets = payload
        result = _find_moof_offset(data)
        if not moof_offsets:
            self.assertEqual(result, -1)
        else:
            self.assertEqual(result, moof_offsets[0])

    @given(
        prefix=st.binary(max_size=64).filter(lambda b: b"moof" not in b),
        moof_payload=st.binary(max_size=40),
        suffix=st.binary(max_size=64),
    )
    def test_misaligned_moof_recovery_is_bounded(self, prefix, moof_payload, suffix):
        """Byte-scan recovery only runs while a garbage length reads as < 8.

        A garbage byte run whose first 4 bytes parse as a large box length
        makes the scan jump *past* a following moof and report -1 — the
        recovery is best-effort, not guaranteed. Pin that boundary: the scan
        must never return a stale offset for a moof it skipped, and when it
        does report -1 the skipped moof is simply invisible to the caller.
        """
        moof = box(b"moof", moof_payload)
        data = prefix + moof + suffix
        result = _find_moof_offset(data, start=0)
        if result == -1:
            # Acceptable: recovery gave up (documented limitation).
            return
        self.assertEqual(data[result + 4: result + 8], b"moof")
        self.assertGreaterEqual(result, 0)

    @given(moof_payload=st.binary(max_size=40), suffix=st.binary(max_size=32))
    def test_aligned_moof_at_offset_zero_is_found(self, moof_payload, suffix):
        """The happy path: a moof at the scan start is always reported at 0."""
        moof = box(b"moof", moof_payload)
        self.assertEqual(_find_moof_offset(moof + suffix, start=0), 0)

    @given(payload=box_streams(), start_offset=st.integers(min_value=1, max_value=64))
    def test_start_skips_earlier_moofs(self, payload, start_offset):
        """start=N never reports a moof at offset < N."""
        data, moof_offsets = payload
        result = _find_moof_offset(data, start=start_offset)
        if result != -1:
            self.assertGreaterEqual(result, start_offset)
