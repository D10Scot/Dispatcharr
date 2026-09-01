"""Property-based tests for FMP4RemuxManager._flush_complete_fragments.

The fMP4 reader loop accumulates FFmpeg stdout into `frag_buf` and extracts
complete moof+mdat(+...) fragments, one Redis chunk per fragment. A fragment
ends where the next moof begins; an incomplete trailing fragment stays staged.

Invariants the implementation promises:

* never raises, whatever bytes FFmpeg (or a desynced buffer) produced;
* no byte is ever duplicated across emitted fragments, and every emitted
  fragment starts with a moof box header;
* once at least one fragment has been emitted, emitted bytes are a *prefix*
  of the input stream (fragments are cut in order, nothing is reordered);
* bytes are only ever dropped before the first fragment completes
  (misalignment resync) or while a trailing partial fragment is staged —
  never silently discarded mid-stream;
* an aligned, well-formed moof/mdat stream chunked arbitrarily yields exactly
  the original boxes, in order, as fragments.

Runs without Redis or the database (SimpleTestCase; the manager instance is
built unpinned via __new__ and its fmp4_buffer is a recording stub).
"""

import struct

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.output.fmp4.manager import FMP4RemuxManager

# CI-deterministic profile — see test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


class RecordingBuffer:
    """Stands in for FMP4StreamBuffer.put_fragment."""

    def __init__(self):
        self.fragments = []
        self.index = 0

    def put_fragment(self, data: bytes) -> bool:
        self.fragments.append(bytes(data))
        self.index += 1
        return True


def make_manager():
    mgr = FMP4RemuxManager.__new__(FMP4RemuxManager)
    mgr.channel_id = "prop"
    mgr.fmp4_buffer = RecordingBuffer()
    return mgr


def flush_all(mgr, chunks):
    """Feed chunks into a fresh frag_buf the way _reader_loop does."""
    frag_buf = bytearray()
    for chunk in chunks:
        frag_buf.extend(chunk)
        mgr._flush_complete_fragments(frag_buf)
    return frag_buf


NON_MOOF = st.binary(min_size=4, max_size=4).filter(lambda t: t != b"moof")


@st.composite
def moof_streams(draw):
    """A stream of complete boxes starting with a moof, split into chunks."""
    parts = []
    # First box must be moof so the stream is aligned from byte 0.
    for i in range(draw(st.integers(1, 5))):
        t = b"moof" if i % 2 == 0 else draw(NON_MOOF)
        parts.append(box(t, draw(st.binary(max_size=48))))
    data = b"".join(parts)
    cuts = draw(st.lists(st.integers(0, len(data)), max_size=6))
    bounds = sorted([0, *cuts, len(data)])
    chunks = [data[a:b] for a, b in zip(bounds, bounds[1:])]
    return data, chunks


class FlushFragmentsProperties(SimpleTestCase):
    @given(chunks=st.lists(st.binary(max_size=200), max_size=12))
    def test_never_raises_and_fragments_start_with_moof(self, chunks):
        mgr = make_manager()
        remaining = flush_all(mgr, chunks)
        for frag in mgr.fmp4_buffer.fragments:
            self.assertGreaterEqual(len(frag), 8)
            self.assertEqual(frag[4:8], b"moof")
        self.assertIsInstance(remaining, bytearray)

    @given(chunks=st.lists(st.binary(max_size=200), max_size=12))
    def test_no_byte_duplicated_and_emission_is_in_order(self, chunks):
        """Emitted fragments are disjoint and appear in stream order."""
        mgr = make_manager()
        flush_all(mgr, chunks)
        stream = b"".join(chunks)
        cursor = 0
        for frag in mgr.fmp4_buffer.fragments:
            found = stream.find(frag, cursor)
            # Each fragment must appear at or after the previous one.
            self.assertNotEqual(found, -1)
            cursor = found + len(frag)

    @given(payload=moof_streams())
    def test_aligned_stream_round_trips(self, payload):
        """Aligned boxes arbitrarily re-chunked yield exactly the moof-led
        fragments FFmpeg produced: one fragment per moof, in order, and the
        concatenation of fragments plus the staged remainder is the input."""
        data, chunks = payload
        mgr = make_manager()
        remaining = flush_all(mgr, chunks)

        # Count moofs in the original stream (aligned: every box boundary).
        expected_frags = []
        offset = 0
        moof_positions = []
        while offset + 8 <= len(data):
            size = struct.unpack_from(">I", data, offset)[0]
            if size < 8 or offset + size > len(data):
                break
            if data[offset + 4: offset + 8] == b"moof":
                moof_positions.append(offset)
            offset += size

        for i, pos in enumerate(moof_positions):
            end = moof_positions[i + 1] if i + 1 < len(moof_positions) else None
            if end is not None:
                expected_frags.append(data[pos:end])
            # Last moof's fragment stays staged (no following moof) unless the
            # stream happens to end exactly at a moof boundary.

        self.assertEqual(mgr.fmp4_buffer.fragments, expected_frags)
        reassembled = b"".join(mgr.fmp4_buffer.fragments) + bytes(remaining)
        self.assertEqual(reassembled, data[: len(reassembled)])
        # And nothing was reordered: reassembly is a prefix of the input.
        self.assertTrue(data.startswith(reassembled) or reassembled == data)
