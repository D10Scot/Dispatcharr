"""Property-based tests for the catch-up HTTP Range helpers in
``apps.timeshift.views``.

These cover the request/response range plumbing the earlier helper fuzzing
(see the ``test_property_*`` suites referenced from the fuzz-hardening issue
for ``apps.timeshift``) did not touch: ``_parse_client_range``,
``_parse_content_range_header``, ``_parse_range_start``,
``_cap_open_ended_range``, ``_map_client_range_through_presentation`` and
``_is_full_restart_range``. Each property states an invariant the
implementation already promises — read from the code, not invented:

* both parsers never raise on arbitrary header text and only ever return
  tuples/dicts of non-negative ints;
* ``_parse_range_start`` always agrees with the first element of
  ``_parse_client_range``;
* ``_cap_open_ended_range`` leaves closed-ended ranges untouched and caps an
  open-ended ``bytes=START-`` to exactly ``max_span_bytes``;
* ``_map_client_range_through_presentation`` is a pure translation by the
  presentation byte base on both bounds;
* ``_is_full_restart_range`` is true exactly for a missing header or
  open-ended ``bytes=0-`` (the two shapes providers answer with a full
  file from byte 0).

Runs derandomized with a fixed example count so CI stays reproducible.
No Redis or database access: every test is a ``SimpleTestCase``.
"""

from hypothesis import given, settings as hyp_settings, strategies as st

from django.test import SimpleTestCase

from apps.timeshift.views import (
    _cap_open_ended_range,
    _is_full_restart_range,
    _map_client_range_through_presentation,
    _parse_client_range,
    _parse_content_range_header,
    _parse_range_start,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class RangeParsingProperties(SimpleTestCase):
    @given(header=st.one_of(st.text(), st.none()))
    def test_client_range_never_raises_and_fields_non_negative(self, header):
        parsed = _parse_client_range(header)
        if parsed is None:
            return
        start, end = parsed
        self.assertGreaterEqual(start, 0)
        if end is not None:
            self.assertGreaterEqual(end, 0)

    @given(header=st.one_of(st.text(), st.none()))
    def test_content_range_never_raises(self, header):
        parsed = _parse_content_range_header(header)
        if parsed is None:
            return
        self.assertGreaterEqual(parsed["start"], 0)
        if parsed["end"] is not None:
            self.assertGreaterEqual(parsed["end"], 0)
        if parsed["total"] is not None:
            self.assertGreaterEqual(parsed["total"], 0)

    @given(header=st.one_of(st.text(), st.none()))
    def test_parse_range_start_agrees_with_full_parse(self, header):
        parsed = _parse_client_range(header)
        start = _parse_range_start(header)
        if parsed is None:
            self.assertIsNone(start)
        else:
            self.assertEqual(start, parsed[0])

    @given(
        start=st.integers(0, 10**12),
        cap=st.integers(1, 10**9),
    )
    def test_cap_open_ended_range_caps_exactly(self, start, cap):
        capped = _cap_open_ended_range(f"bytes={start}-", cap)
        start_s, end_s = capped[len("bytes="):].split("-", 1)
        self.assertEqual(int(start_s), start)
        self.assertEqual(int(end_s) - int(start_s) + 1, cap)

    @given(
        start=st.integers(0, 10**12),
        end=st.integers(0, 10**12),
        cap=st.integers(1, 10**9),
    )
    def test_cap_open_ended_range_leaves_closed_ranges_untouched(
        self, start, end, cap
    ):
        header = f"bytes={start}-{end}"
        self.assertEqual(_cap_open_ended_range(header, cap), header)

    @given(
        start=st.integers(0, 10**12),
        end=st.one_of(st.integers(0, 10**12), st.none()),
        base=st.integers(0, 10**9),
    )
    def test_presentation_mapping_shifts_both_bounds(self, start, end, base):
        """Presentation mapping is a pure translation: absolute - client == base."""
        header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        mapped = _map_client_range_through_presentation(header, base)
        abs_start, abs_end = _parse_client_range(mapped)
        self.assertEqual(abs_start, base + start)
        if end is None:
            self.assertIsNone(abs_end)
        else:
            self.assertEqual(abs_end, base + end)

    @given(header=st.one_of(st.text(), st.none()))
    def test_full_restart_is_only_plain_get_or_zero_open_ended(self, header):
        """A restart means 'serve from byte 0', so start must be 0, open-ended."""
        result = _is_full_restart_range(header)
        if not header:
            self.assertTrue(result)
            return
        parsed = _parse_client_range(header)
        if parsed is None:
            self.assertFalse(result)
            return
        start, end = parsed
        self.assertEqual(result, start == 0 and end is None)
