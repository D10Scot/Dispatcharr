"""Property tests for the XMLTV export window helpers in ``apps/output/epg.py``.

Surfaces (``file:line`` at a54b09a9):

- ``_programme_overlaps_export_window`` (``apps/output/epg.py:34``): the filter every
  programme, real or dummy, passes through on its way into ``/output/epg``.
- ``_ceil_to_half_hour`` (``apps/output/epg.py:42``): where a custom dummy EPG starts
  filling the export window when its event lies outside it.
- ``generate_fallback_programs`` (``apps/output/epg.py:83``): the grid a custom dummy
  source emits when its title pattern does not match.

Closes the ``apps/output/epg.py`` half of #92 (dups #210, #162).
"""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.output.epg import (
    _ceil_to_half_hour,
    _programme_overlaps_export_window,
    generate_fallback_programs,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Instants within +/- 400 days of 2026-01-01, at one-second resolution, always
# UTC-aware: the export computes lookback and cutoff from django's timezone.now().
aware_instants = st.integers(-400 * 86400, 400 * 86400).map(
    lambda s: _EPOCH + timedelta(seconds=s)
)
# Microsecond-resolution naive and aware datetimes for the rounding helper.
any_datetimes = st.one_of(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
    st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(timezone.utc),
    ),
)


class ProgrammeOverlapsExportWindowProperties(SimpleTestCase):
    """The programme is the closed interval [start, end]; the window is [lookback, cutoff)."""

    @given(
        start=aware_instants,
        length=st.integers(0, 3 * 86400),
        lookback=aware_instants,
        window=st.one_of(st.none(), st.integers(1, 30 * 86400)),
    )
    # A programme that ends exactly at the lookback boundary still overlaps (end >= lookback).
    @example(start=_EPOCH - timedelta(hours=1), length=3600, lookback=_EPOCH, window=None)
    # A programme that starts exactly at the cutoff does not (start < cutoff).
    @example(start=_EPOCH, length=3600, lookback=_EPOCH - timedelta(days=1), window=86400)
    def test_overlap_decision_is_closed_programme_against_half_open_window(
        self, start, length, lookback, window
    ):
        # The export builds a non-empty window: cutoff is now + num_days (or None when
        # num_days is 0) and lookback is now - prev_days (apps/output/epg.py:1192-1193).
        cutoff = None if window is None else lookback + timedelta(seconds=window)
        end = start + timedelta(seconds=length)
        # Oracle: some instant t with start <= t <= end and lookback <= t (< cutoff) exists.
        latest_admissible = end if cutoff is None else min(end, cutoff - timedelta(microseconds=1))
        earliest_admissible = max(start, lookback)
        expected = earliest_admissible <= latest_admissible
        self.assertEqual(
            _programme_overlaps_export_window(start, end, lookback, cutoff), expected
        )

    @given(
        lookback=aware_instants,
        span=st.integers(1, 30 * 86400),
        offset=st.floats(0, 1, exclude_max=True),
        length=st.floats(0, 1),
    )
    def test_programme_wholly_inside_the_window_always_overlaps(
        self, lookback, span, offset, length
    ):
        cutoff = lookback + timedelta(seconds=span)
        start = lookback + timedelta(seconds=int(span * offset))
        end = start + timedelta(seconds=int((cutoff - start).total_seconds() * length))
        self.assertTrue(_programme_overlaps_export_window(start, end, lookback, cutoff))
        self.assertTrue(_programme_overlaps_export_window(start, end, lookback, None))


class CeilToHalfHourProperties(SimpleTestCase):
    @given(dt=any_datetimes)
    @example(dt=datetime(2026, 1, 1, 10, 0, 0))  # already aligned: unchanged
    @example(dt=datetime(2026, 1, 1, 10, 0, 30))  # 30 s past :00 goes to :30, not :00
    @example(dt=datetime(2026, 1, 1, 10, 0, 0, 500))  # sub-second only: truncated, stays :00
    @example(dt=datetime(2026, 1, 1, 23, 59, 59))  # rolls over midnight
    def test_result_is_the_least_half_hour_boundary_not_before_the_second_truncated_input(
        self, dt
    ):
        result = _ceil_to_half_hour(dt)
        floor_second = dt.replace(microsecond=0)
        # Independent oracle: whole seconds since the input's own midnight, ceiled to 1800.
        midnight = floor_second.replace(hour=0, minute=0, second=0)
        secs = int((floor_second - midnight).total_seconds())
        expected = midnight + timedelta(seconds=-(-secs // 1800) * 1800)
        self.assertEqual(result, expected)
        self.assertEqual(result.tzinfo, dt.tzinfo)
        self.assertIn(result.minute, (0, 30))
        self.assertEqual((result.second, result.microsecond), (0, 0))

    @given(dt=any_datetimes)
    def test_ceil_is_idempotent(self, dt):
        once = _ceil_to_half_hour(dt)
        self.assertEqual(_ceil_to_half_hour(once), once)


class GenerateFallbackProgramsProperties(SimpleTestCase):
    @given(
        now=aware_instants,
        num_days=st.integers(0, 4),
        length=st.integers(1, 30),
        title=st.text(max_size=20),
        description=st.text(max_size=20),
        channel_name=st.text(min_size=1, max_size=20),
    )
    def test_grid_geometry_and_template_fallbacks(
        self, now, num_days, length, title, description, channel_name
    ):
        programs = generate_fallback_programs(
            7, channel_name, now, num_days, length, title, description
        )
        per_day = len(range(0, 24, length))  # hour offsets 0, length, ... < 24
        self.assertEqual(len(programs), num_days * per_day)
        for i, program in enumerate(programs):
            day, slot = divmod(i, per_day)
            expected_start = now + timedelta(days=day, hours=slot * length)
            self.assertEqual(program["start_time"], expected_start)
            self.assertEqual(program["end_time"] - program["start_time"], timedelta(hours=length))
            self.assertEqual(program["channel_id"], 7)
            self.assertEqual(program["title"], title or channel_name)
            self.assertEqual(
                program["description"],
                description or f"EPG information is currently unavailable for {channel_name}",
            )
