"""Property-based tests for M3U auto-sync channel numbering helpers.

These encode invariants read directly from the implementations in
apps/m3u/tasks.py (no invented guarantees):

``_next_available_number(used, start, end=None)``:
  - returns the smallest integer ``>= start`` not present in ``used``;
  - never returns a member of ``used``;
  - never returns a value ``< start``;
  - when ``end`` is given, returns ``None`` iff every integer in
    ``[start, end]`` is used, else a value ``<= end``;
  - with ``end=None`` it always terminates and returns an int.

``_pick_target_number(mode, ...)``:
  - provider mode: a free provider number is used verbatim, and the result is
    never in ``used``;
  - provider mode with a used/absent provider number falls back into
    ``[fallback_start, end_number]`` (or ``None`` when that range is full);
  - next_available mode always starts searching at 1 and ignores ``end_number``
    (its UI exposes no range, so a stale End must not cap it);
  - fixed mode searches from the cursor and respects ``end_number``;
  - across all modes the result is either ``None`` or not in ``used``.

All tests are ``SimpleTestCase``-based (no DB, no Redis) and use a derandomized
CI profile so runs stay fast and reproducible.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import _next_available_number, _pick_target_number

# CI-deterministic profile (registered/loaded at import; the Django test runner
# has no pytest-style conftest hook). derandomize keeps runs reproducible;
# deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Keep numbers small and non-negative so `used` clusters actually collide and
# the while-loop terminates quickly even in the worst case.
_NUM = st.integers(min_value=0, max_value=40)
_USED = st.frozensets(_NUM, max_size=45)
_START = st.integers(min_value=0, max_value=40)


class NextAvailableNumberPropertyTests(SimpleTestCase):
    @given(used=_USED, start=_START)
    def test_result_is_free_and_not_below_start(self, used, start):
        n = _next_available_number(set(used), start)
        self.assertIsNotNone(n)
        self.assertNotIn(n, used)
        self.assertGreaterEqual(n, start)

    @given(used=_USED, start=_START)
    def test_result_is_the_smallest_free_number(self, used, start):
        """Every integer in [start, result) must be used."""
        n = _next_available_number(set(used), start)
        for candidate in range(start, n):
            self.assertIn(candidate, used)

    @given(used=_USED, start=_START, end=st.integers(min_value=0, max_value=45))
    def test_bounded_search_respects_end(self, used, start, end):
        n = _next_available_number(set(used), start, end=end)
        if n is None:
            # Exhausted: every integer in [start, end] is used.
            for candidate in range(start, end + 1):
                self.assertIn(candidate, used)
        else:
            self.assertLessEqual(n, end)
            self.assertNotIn(n, used)
            self.assertGreaterEqual(n, start)

    @given(used=_USED, start=_START)
    def test_unbounded_search_always_terminates_with_int(self, used, start):
        n = _next_available_number(set(used), start)
        self.assertIsInstance(n, int)


def _stream(chno):
    return SimpleNamespace(stream_chno=chno)


class PickTargetNumberPropertyTests(SimpleTestCase):
    @given(used=_USED, chno=st.one_of(st.none(), _NUM))
    def test_free_provider_number_used_verbatim(self, used, chno):
        assume(chno is not None and chno not in used)
        result = _pick_target_number(
            "provider", _stream(chno), set(used), fixed_cursor=1,
            fallback_start=1, end_number=None,
        )
        self.assertEqual(result, chno)
        self.assertNotIn(result, used)

    @given(used=_USED, chno=st.one_of(st.none(), _NUM), end=st.integers(0, 45))
    def test_provider_fallback_within_range_or_none(self, used, chno, end):
        """Provider number absent/used: fall back into [fallback_start, end]."""
        assume(chno is None or chno in used)
        fallback_start = 2
        result = _pick_target_number(
            "provider", _stream(chno), set(used), fixed_cursor=1,
            fallback_start=fallback_start, end_number=end,
        )
        if result is None:
            for candidate in range(fallback_start, end + 1):
                self.assertIn(candidate, used)
        else:
            self.assertNotIn(result, used)
            self.assertGreaterEqual(result, fallback_start)
            self.assertLessEqual(result, end)

    @given(used=_USED, end=st.integers(0, 45))
    def test_next_available_ignores_end_and_starts_at_one(self, used, end):
        """next_available has no range UI: a stale End must not cap it."""
        result = _pick_target_number(
            "next_available", _stream(None), set(used), fixed_cursor=7,
            fallback_start=9, end_number=end,
        )
        self.assertIsNotNone(result)
        self.assertNotIn(result, used)
        self.assertGreaterEqual(result, 1)

    @given(used=_USED, cursor=_START, end=st.integers(0, 45))
    def test_fixed_mode_respects_cursor_and_end(self, used, cursor, end):
        result = _pick_target_number(
            "fixed", _stream(None), set(used), fixed_cursor=cursor,
            fallback_start=1, end_number=end,
        )
        if result is None:
            for candidate in range(cursor, end + 1):
                self.assertIn(candidate, used)
        else:
            self.assertNotIn(result, used)
            self.assertGreaterEqual(result, cursor)
            self.assertLessEqual(result, end)

    @given(
        used=_USED,
        mode=st.sampled_from(["provider", "next_available", "fixed"]),
        chno=st.one_of(st.none(), _NUM),
    )
    def test_result_never_in_used_any_mode(self, used, mode, chno):
        result = _pick_target_number(
            mode, _stream(chno), set(used), fixed_cursor=1,
            fallback_start=1, end_number=None,
        )
        if result is not None:
            self.assertNotIn(result, used)
