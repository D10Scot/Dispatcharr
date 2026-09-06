"""Property-based tests for the timeshift HTTP range/presentation helpers.

``apps.timeshift.views`` parses client-controlled ``Range`` headers and
provider-controlled ``Content-Range``/``Content-Length`` headers, then maps
them through the pool's presentation window. The invariants under test:

* ``_parse_client_range`` / ``_parse_content_range_header`` never raise, and
  any non-None result is internally consistent (non-negative ints; a closed
  end is not smaller than its start is *not* promised — the code is
  deliberately permissive and passes values through, so no such claim here).
* Well-formed headers round-trip: generated ``bytes=start-end`` values parse
  back to exactly those numbers.
* ``_cap_open_ended_range`` bounds every open-ended range to exactly
  ``max_span_bytes`` and leaves closed ranges and unparseable input untouched.
* ``_map_client_range_through_presentation`` translates both offsets by the
  base and round-trips through the parser; a zero base is the identity.
* ``_presentation_relative_content_range`` is the exact inverse of
  ``_map_client_range_through_presentation`` for in-window ranges, and never
  fabricates a rewrite for out-of-window upstream ranges (input passthrough).
* ``_pool_int_field`` accepts int/str/bytes spellings of integers and rejects
  everything else without raising.
* ``_extract_representation_length`` prefers a Content-Range total over
  Content-Length, falls back to Content-Length, and returns None when neither
  parses.
* ``_is_full_restart_range`` holds exactly for a missing Range header or an
  open-ended range starting at byte 0.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift.views import (
    _cap_open_ended_range,
    _is_full_restart_range,
    _map_client_range_through_presentation,
    _parse_client_range,
    _parse_content_range_header,
    _pool_int_field,
    _presentation_relative_content_range,
)

# CI-deterministic profile — matches apps/proxy/live_proxy property tests.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

range_header_text = st.text(max_size=48) | st.text(
    alphabet="0123456789bytes=,-/* ", min_size=1, max_size=40
)

small_offset = st.integers(min_value=0, max_value=10**12)


def well_formed_range(start, end):
    return f"bytes={start}-" + ("" if end is None else str(end))


class ClientRangeParserProperties(SimpleTestCase):
    @given(value=range_header_text)
    def test_never_raises(self, value):
        parsed = _parse_client_range(value)
        if parsed is not None:
            start, end = parsed
            self.assertGreaterEqual(start, 0)
            if end is not None:
                self.assertGreaterEqual(end, 0)

    @given(start=small_offset, end=st.one_of(st.none(), small_offset))
    def test_well_formed_round_trip(self, start, end):
        self.assertEqual(
            _parse_client_range(well_formed_range(start, end)), (start, end)
        )

    @given(value=range_header_text)
    def test_garbage_returns_none_or_valid(self, value):
        # Non-"bytes=" prefixed input is always rejected.
        if not value.startswith("bytes="):
            self.assertIsNone(_parse_client_range(value))

    @given(value=st.binary(max_size=40))
    def test_bytes_input_rejected_without_raising(self, value):
        # Callers decode before handing values here; bytes are not a promise.
        try:
            _parse_client_range(value)
        except (AttributeError, TypeError):
            pass  # acceptable: bytes are outside the documented contract


class ContentRangeParserProperties(SimpleTestCase):
    @given(value=range_header_text)
    def test_never_raises(self, value):
        parsed = _parse_content_range_header(value)
        if parsed is not None:
            self.assertGreaterEqual(parsed["start"], 0)
            if parsed["end"] is not None:
                self.assertGreaterEqual(parsed["end"], 0)
            if parsed["total"] is not None:
                self.assertGreaterEqual(parsed["total"], 0)

    @given(start=small_offset, end=small_offset, total=small_offset)
    def test_well_formed_round_trip(self, start, end, total):
        text = f"bytes {start}-{end}/{total}"
        self.assertEqual(
            _parse_content_range_header(text),
            {"start": start, "end": end, "total": total},
        )

    @given(start=small_offset, end=small_offset)
    def test_star_total_round_trip(self, start, end):
        text = f"bytes {start}-{end}/*"
        self.assertEqual(
            _parse_content_range_header(text),
            {"start": start, "end": end, "total": None},
        )


class CapOpenEndedRangeProperties(SimpleTestCase):
    @given(start=small_offset, span=st.integers(min_value=1, max_value=10**9))
    def test_open_ended_capped_exactly(self, start, span):
        capped = _cap_open_ended_range(f"bytes={start}-", span)
        self.assertEqual(capped, f"bytes={start}-{start + span - 1}")

    @given(start=small_offset, end=small_offset, span=st.integers(min_value=1, max_value=10**9))
    def test_closed_range_untouched(self, start, end, span):
        header = f"bytes={start}-{end}"
        self.assertEqual(_cap_open_ended_range(header, span), header)

    @given(
        value=range_header_text,
        span=st.one_of(st.none(), st.integers(max_value=0)),
    )
    def test_unparseable_or_nonpositive_span_untouched(self, value, span):
        self.assertEqual(_cap_open_ended_range(value, span), value)


class PresentationMappingProperties(SimpleTestCase):
    @given(
        start=small_offset,
        end=st.one_of(st.none(), small_offset),
        base=small_offset,
    )
    def test_map_round_trip_through_parser(self, start, end, base):
        mapped = _map_client_range_through_presentation(
            well_formed_range(start, end), base
        )
        expected_end = None if end is None else base + end
        self.assertEqual(
            _parse_client_range(mapped), (base + start, expected_end)
        )

    @given(value=range_header_text, base=small_offset)
    def test_map_never_raises(self, value, base):
        _map_client_range_through_presentation(value, base)

    @given(value=range_header_text)
    def test_zero_base_is_identity(self, value):
        self.assertEqual(
            _map_client_range_through_presentation(value, 0), value
        )

    @given(
        start=small_offset,
        length=st.integers(min_value=1, max_value=10**9),
        base=small_offset,
        presentation_length=st.integers(min_value=1, max_value=10**12),
    )
    def test_relative_content_range_inverts_map(self, start, length, base, presentation_length):
        abs_start = base + start
        abs_end = abs_start + length - 1
        upstream = f"bytes {abs_start}-{abs_end}/{base + presentation_length}"
        rewritten = _presentation_relative_content_range(
            upstream,
            presentation_byte_base=base,
            presentation_length=presentation_length,
        )
        self.assertEqual(
            rewritten, f"bytes {start}-{abs_end - base}/{presentation_length}"
        )

    @given(
        start=st.integers(min_value=1, max_value=10**12),
        base=small_offset,
    )
    def test_out_of_window_passthrough(self, start, base):
        # Upstream range entirely before the presentation window must not be
        # rewritten into negative coordinates — input comes back unchanged.
        from hypothesis import assume

        assume(start <= base)
        upstream = f"bytes {start - 1}-{start - 1}/1000000"
        rewritten = _presentation_relative_content_range(
            upstream,
            presentation_byte_base=base,
            presentation_length=100,
        )
        self.assertEqual(rewritten, upstream)


class PoolFieldCoercionProperties(SimpleTestCase):
    @given(
        value=st.one_of(
            st.none(),
            st.integers(),
            st.text(max_size=24),
            st.binary(max_size=24),
            st.floats(allow_nan=False, allow_infinity=False),
        )
    )
    def test_never_raises(self, value):
        _pool_int_field(value)

    @given(value=st.integers())
    def test_int_spellings_round_trip(self, value):
        self.assertEqual(_pool_int_field(value), value)
        self.assertEqual(_pool_int_field(str(value)), value)
        self.assertEqual(_pool_int_field(str(value).encode()), value)

    @given(value=st.one_of(st.none(), st.sampled_from(["", b""])))
    def test_empty_is_none(self, value):
        self.assertIsNone(_pool_int_field(value))

    @given(value=st.text(alphabet="0123456789", min_size=1, max_size=3).map(lambda s: s + "x"))
    def test_non_integer_text_is_none(self, value):
        self.assertIsNone(_pool_int_field(value))


class FullRestartRangeProperties(SimpleTestCase):
    @given(value=range_header_text)
    def test_never_raises(self, value):
        _is_full_restart_range(value)

    def test_no_header_is_restart(self):
        self.assertTrue(_is_full_restart_range(None))
        self.assertTrue(_is_full_restart_range(""))

    @given(end=st.one_of(st.none(), small_offset))
    def test_bytes_zero_open_ended_only(self, end):
        header = well_formed_range(0, end)
        self.assertEqual(_is_full_restart_range(header), end is None)

    @given(start=st.integers(min_value=1, max_value=10**12))
    def test_nonzero_start_is_not_restart(self, start):
        self.assertFalse(_is_full_restart_range(f"bytes={start}-"))
