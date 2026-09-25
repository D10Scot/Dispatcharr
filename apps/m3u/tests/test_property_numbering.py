"""Property tests for auto-sync channel numbering and the batch-count summary
(issues #218, #145, #69).

Surfaces, with their line at seed a54b09a9:

- ``_next_available_number`` (``apps/m3u/tasks.py:1907``): the smallest free
  integer at or above ``start``, or ``None`` when an inclusive ``end`` is
  exhausted.
- ``_pick_target_number`` (``apps/m3u/tasks.py:1927``): the per-mode claim,
  whose docstring states each mode's contract.
- ``_batch_stream_count_message`` / ``_parse_batch_stream_counts``
  (``apps/m3u/tasks.py:1070``, ``:1077``): the batch workers' summary string
  and the parser that totals it.

Every oracle below is a brute-force scan over a small integer range, written
in the test, never a call back into the helper.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _batch_stream_count_message,
    _next_available_number,
    _parse_batch_stream_counts,
    _pick_target_number,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

used_sets = st.sets(st.integers(min_value=-5, max_value=60), max_size=50)
starts = st.integers(min_value=-5, max_value=40)
ends = st.none() | st.integers(min_value=-5, max_value=60)


def _brute_force_next(used, start, end):
    """Smallest n >= start not in used, or None past an inclusive end."""
    n = start
    while True:
        if end is not None and n > end:
            return None
        if n not in used:
            return n
        n += 1


class NextAvailableNumberProperties(SimpleTestCase):
    @given(used=used_sets, start=starts, end=ends)
    def test_next_available_is_the_smallest_free_number_within_the_bound(self, used, start, end):
        self.assertEqual(
            _next_available_number(used, start, end=end),
            _brute_force_next(used, start, end),
        )

    @given(start=st.integers(min_value=0, max_value=40), span=st.integers(min_value=0, max_value=20))
    def test_none_exactly_when_the_inclusive_range_is_full(self, start, span):
        end = start + span
        full = set(range(start, end + 1))
        self.assertIsNone(_next_available_number(full, start, end=end))
        self.assertEqual(_next_available_number(full - {end}, start, end=end), end)


streams = st.builds(SimpleNamespace, stream_chno=st.none() | st.integers(min_value=1, max_value=60))
modes = st.sampled_from(("provider", "next_available", "fixed"))


class PickTargetNumberProperties(SimpleTestCase):
    @given(
        mode=modes,
        stream=streams,
        used=used_sets,
        cursor=st.integers(min_value=1, max_value=40),
        fallback=st.integers(min_value=1, max_value=40),
        end=ends,
    )
    def test_no_mode_ever_claims_a_used_number(self, mode, stream, used, cursor, fallback, end):
        result = _pick_target_number(mode, stream, used, cursor, fallback, end_number=end)
        if result is not None:
            self.assertNotIn(result, used)

    @given(stream=streams, used=used_sets, fallback=st.integers(min_value=1, max_value=40), end=ends)
    def test_provider_mode_uses_a_free_provider_number_verbatim_else_falls_back_in_range(
        self, stream, used, fallback, end
    ):
        result = _pick_target_number("provider", stream, used, 1, fallback, end_number=end)
        if stream.stream_chno is not None and stream.stream_chno not in used:
            # End bounds only the fallback: a free provider number is used as-is.
            self.assertEqual(result, stream.stream_chno)
        else:
            self.assertEqual(result, _brute_force_next(used, fallback, end))

    @given(used=used_sets, cursor=st.integers(min_value=1, max_value=40), end=st.integers(min_value=-5, max_value=60))
    def test_next_available_mode_starts_at_one_and_ignores_end(self, used, cursor, end):
        result = _pick_target_number(
            "next_available", SimpleNamespace(stream_chno=None), used, cursor, 99, end_number=end
        )
        self.assertEqual(result, _brute_force_next(used, 1, None))

    @given(used=used_sets, cursor=st.integers(min_value=1, max_value=40), end=ends)
    def test_fixed_mode_counts_up_from_the_cursor_bounded_by_end(self, used, cursor, end):
        result = _pick_target_number(
            "fixed", SimpleNamespace(stream_chno=5), used, cursor, 99, end_number=end
        )
        self.assertEqual(result, _brute_force_next(used, cursor, end))


class BatchStreamCountProperties(SimpleTestCase):
    counts = st.integers(min_value=0, max_value=10**9)

    @given(created=counts, updated=counts, unchanged=counts)
    def test_a_built_summary_parses_back_to_its_counts(self, created, updated, unchanged):
        message = _batch_stream_count_message(created, updated, unchanged)
        self.assertEqual(_parse_batch_stream_counts(message), (created, updated, unchanged))

    @given(value=st.none() | st.integers() | st.lists(st.integers(), max_size=3) | st.binary(max_size=10))
    def test_non_string_results_count_as_zero(self, value):
        self.assertEqual(_parse_batch_stream_counts(value), (0, 0, 0))

    @given(text=st.text(max_size=120))
    def test_arbitrary_text_is_total_and_all_or_nothing(self, text):
        parsed = _parse_batch_stream_counts(text)
        self.assertEqual(len(parsed), 3)
        self.assertTrue(all(isinstance(n, int) and n >= 0 for n in parsed))
        if "created" not in text or "updated" not in text or "unchanged" not in text:
            # A missing counter zeroes all three rather than returning a partial count.
            self.assertEqual(parsed, (0, 0, 0))
