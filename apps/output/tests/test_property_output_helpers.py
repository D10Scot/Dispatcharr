"""Property-based tests for pure output-surface helpers.

Covers the small pure functions that sit behind the M3U/EPG/XC output
endpoints and whose inputs are at least partly provider- or
operator-controlled:

- ``_programme_overlaps_export_window`` decides which programmes make the
  XMLTV export window; its contract is a pure boolean predicate over the
  (start, end, lookback, cutoff) datetimes.
- ``_ceil_to_half_hour`` aligns export window starts to :00/:30. The existing
  unit tests in test_views.py bless second-granularity semantics: the result
  must be >= the input with microseconds stripped, aligned to a 30-minute
  boundary, and never more than 30 minutes ahead of the stripped input.
- ``generate_fallback_programs`` builds the dummy-EPG grid; for a positive
  integer program length every program must span exactly that many hours with
  start < end, and program count must equal num_days * (24 // len) when len
  divides 24.
- ``format_duration_hms`` renders ``episode.duration_secs`` (provider JSON,
  stored in an IntegerField) into the XC API's display string; for any
  non-negative duration it must produce a zero-padded HH:MM:SS string whose
  fields round-trip back to the input seconds.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.output.epg import (
    _ceil_to_half_hour,
    _programme_overlaps_export_window,
    generate_fallback_programs,
)
from apps.output.views import format_duration_hms

# CI-deterministic profile — see apps/proxy/live_proxy/tests/
# test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Datetimes bounded away from datetime.min/max so timedelta arithmetic inside
# the implementation cannot overflow.
safe_datetimes = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 12, 31),
    timezones=st.just(timezone.utc),
)


class ProgrammeWindowProperties(SimpleTestCase):
    @given(
        start=safe_datetimes,
        end=safe_datetimes,
        lookback=safe_datetimes,
        cutoff=safe_datetimes | st.none(),
    )
    def test_window_predicate_matches_spec(
        self, start, end, lookback, cutoff
    ):
        result = _programme_overlaps_export_window(start, end, lookback, cutoff)
        self.assertIs(result, isinstance(result, bool) and result)
        # The implementation is an exact two-clause predicate; recompute it
        # independently and require agreement for every input.
        expected = not (end < lookback) and not (
            cutoff is not None and start >= cutoff
        )
        self.assertEqual(result, expected)


class CeilToHalfHourProperties(SimpleTestCase):
    @given(dt=safe_datetimes)
    def test_result_is_aligned_and_not_before_stripped_input(self, dt):
        aligned = _ceil_to_half_hour(dt)
        stripped = dt.replace(microsecond=0)
        self.assertEqual(aligned.second, 0)
        self.assertEqual(aligned.microsecond, 0)
        self.assertIn(aligned.minute % 30, (0,))
        self.assertEqual(aligned.minute // 30 * 30, aligned.minute)
        # Blessed by test_views.OutputEPGHelperTest: never before the input
        # truncated to second granularity.
        self.assertGreaterEqual(aligned, stripped)
        # And never more than one half-hour step ahead of it.
        self.assertLessEqual(aligned - stripped, timedelta(minutes=30))

    @given(dt=safe_datetimes)
    def test_already_aligned_input_is_unchanged(self, dt):
        dt = dt.replace(second=0, microsecond=0)
        dt = dt.replace(minute=(dt.minute // 30) * 30)
        self.assertEqual(_ceil_to_half_hour(dt), dt)


class FallbackProgramGridProperties(SimpleTestCase):
    @given(
        num_days=st.integers(min_value=1, max_value=7),
        program_length=st.integers(min_value=1, max_value=24),
        now=safe_datetimes,
        channel_name=st.text(max_size=60),
    )
    def test_grid_geometry(self, num_days, program_length, now, channel_name):
        programs = generate_fallback_programs(
            1,
            channel_name,
            now,
            num_days,
            program_length,
            "",
            "",
        )
        expected_per_day = len(range(0, 24, program_length))
        self.assertEqual(len(programs), num_days * expected_per_day)
        for prog in programs:
            self.assertEqual(prog["channel_id"], 1)
            self.assertEqual(
                prog["end_time"] - prog["start_time"],
                timedelta(hours=program_length),
            )
            self.assertGreater(prog["end_time"], prog["start_time"])
            self.assertGreaterEqual(prog["start_time"], now)


class FormatDurationProperties(SimpleTestCase):
    @given(seconds=st.integers(min_value=0, max_value=10**9))
    def test_non_negative_round_trips(self, seconds):
        rendered = format_duration_hms(seconds)
        hours, minutes, secs = rendered.split(":")
        self.assertEqual(len(hours), 2 if seconds < 360000 else len(hours))
        self.assertTrue(minutes.isdigit() and secs.isdigit())
        self.assertLess(int(minutes), 60)
        self.assertLess(int(secs), 60)
        total = int(hours) * 3600 + int(minutes) * 60 + int(secs)
        self.assertEqual(total, seconds)

    @given(value=st.none() | st.floats(allow_nan=False, allow_infinity=False))
    def test_none_and_float_inputs_do_not_raise(self, value):
        assume(value is None or abs(value) < 10**15)
        rendered = format_duration_hms(value)
        self.assertIsInstance(rendered, str)
