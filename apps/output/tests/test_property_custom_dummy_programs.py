"""Property tests for ``generate_custom_dummy_programs`` (``apps/output/epg.py:258``).

A custom dummy EPG source runs operator-configured regexes over provider-controlled
channel names. Whatever a name makes those regexes capture, generation must return
programmes rather than raise: the export loop that calls it (``apps/output/epg.py:1652-1661``)
has no per-channel guard, so one raise truncates ``/output/epg`` for every client.

These properties hold after PR C-1 (#90, dup #211), which range-checks the captured
time and date. The counterexamples from those issues are pinned as ``@example`` rows.

Closes the custom-dummy half of #92 (dups #210, #162).
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.output.epg import generate_custom_dummy_programs

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# The documented dummy-EPG pattern shapes (#90's repro), widened with -? so a provider
# name can capture a negative value as well as an overlong one.
TIME_PATTERN = r"(?<hour>-?\d+):(?<minute>-?\d+)(?<ampm>am|pm|AM|PM)?"
DATE_PATTERN = r"(?<month>-?\d+)/(?<day>-?\d+)(?:/(?<year>-?\d+))?"
MONTH_ONLY_PATTERN = r"M(?<month>-?\d+)"

# `now` is passed in by the caller (hour-aligned UTC in generate_dummy_programs);
# drawn across two years so the 29th-31st of every month is reachable, which is
# what a month-only date pattern defaults its day from.
nows = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31, 23)
).map(lambda d: d.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc))

captured_ints = st.one_of(
    st.integers(-99, 199),
    st.integers(10**18, 10**22),  # overlong digit runs (#211's 20-digit minute)
)
years = st.one_of(st.integers(-5, 3000), st.sampled_from([0, 1, 9999, 10000, 99999]))
zones = st.sampled_from(["UTC", "US/Eastern", "Europe/London", "Asia/Kolkata"])


def _props(**extra):
    props = {"title_pattern": r"(?<title>.*)", "program_duration": 60}
    props.update(extra)
    return props


def _assert_well_formed(test, programs):
    test.assertIsInstance(programs, list)
    for program in programs:
        test.assertIsNotNone(program["start_time"].tzinfo)
        test.assertGreater(program["end_time"], program["start_time"])


class CustomDummyCaptureNeverRaises(SimpleTestCase):
    def setUp(self):
        # Every rejected capture logs a WARNING by design; 200 examples of them is noise.
        patcher = mock.patch("apps.output.epg.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(
        hour=captured_ints,
        minute=captured_ints,
        ampm=st.sampled_from(["", "am", "pm", "AM"]),
        date=st.one_of(st.none(), st.tuples(captured_ints, captured_ints, st.none() | years)),
        tz=zones,
        now=nows,
        num_days=st.integers(1, 3),
        window=st.booleans(),
    )
    # #90: minute 75 -> "ValueError: minute must be in 0..59" at seed.
    @example(hour=10, minute=75, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #90: hour -1.
    @example(hour=-1, minute=30, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #211: minute 99, and a 20-digit minute -> OverflowError at seed.
    @example(hour=10, minute=99, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=10, minute=99999999999999999999, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #90/#211: 2/31 -> "day is out of range for month".
    @example(hour=10, minute=30, ampm="", date=(2, 31, None), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # C-1: 13:30pm on the 12-hour arm -> hour 25.
    @example(hour=13, minute=30, ampm="pm", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # C-1: year 0 and year 99999.
    @example(hour=10, minute=30, ampm="", date=(1, 2, 0), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=10, minute=30, ampm="", date=(1, 2, 99999), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # Found by this property on C-1 as first planned (1 <= year <= 9999): the edge years
    # overflow after the range check, at the +program_duration (apps/output/epg.py:671)
    # and at pytz localize in a zone east of UTC (apps/output/epg.py:572).
    @example(hour=23, minute=30, ampm="", date=(12, 31, 9999), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=0, minute=10, ampm="", date=(1, 1, 1), tz="Asia/Kolkata",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    def test_any_captured_time_or_date_yields_programmes_not_an_exception(
        self, hour, minute, ampm, date, tz, now, num_days, window
    ):
        name = f"Ch {hour}:{minute}{ampm}"
        extra = {"time_pattern": TIME_PATTERN, "timezone": tz}
        if date is not None:
            month, day, year = date
            name += f" {month}/{day}" + ("" if year is None else f"/{year}")
            extra["date_pattern"] = DATE_PATTERN
        # window=True is the /output/epg export call shape (apps/output/epg.py:1654-1661).
        lookback = now - timedelta(days=1) if window else None
        cutoff = now + timedelta(days=num_days) if window else None
        programs = generate_custom_dummy_programs(
            1, name, now, num_days, _props(**extra),
            export_lookback=lookback, export_cutoff=cutoff,
        )
        _assert_well_formed(self, programs)

    @given(hour=st.integers(0, 23), minute=st.integers(0, 59),
           month=captured_ints, now=nows)
    # C-1 (found reading apps/output/epg.py:476,504): a month-only pattern defaults the
    # day to now.day, so on the 31st a month of 30 days or fewer raised.
    @example(hour=10, minute=30, month=2, now=datetime(2026, 1, 31, 12, tzinfo=timezone.utc))
    @example(hour=10, minute=30, month=4, now=datetime(2026, 3, 31, 12, tzinfo=timezone.utc))
    def test_month_only_capture_never_builds_an_impossible_date(self, hour, minute, month, now):
        programs = generate_custom_dummy_programs(
            1, f"Ch {hour}:{minute:02d} M{month}", now, 1,
            _props(time_pattern=TIME_PATTERN, date_pattern=MONTH_ONLY_PATTERN),
        )
        _assert_well_formed(self, programs)


class TwelveHourCaptureMatchesTwentyFourHour(SimpleTestCase):
    """#210: the 12h -> 24h conversion places the event at the same instant as the
    equivalent 24-hour capture, by comparing two code paths of the function."""

    def setUp(self):
        patcher = mock.patch("apps.output.epg.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(hour12=st.integers(1, 12), minute=st.integers(0, 59),
           ampm=st.sampled_from(["am", "pm"]), tz=zones, now=nows,
           days_ahead=st.integers(0, 5))
    @example(hour12=12, minute=0, ampm="am", tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), days_ahead=1)  # midnight
    @example(hour12=12, minute=0, ampm="pm", tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), days_ahead=1)  # noon
    def test_same_programme_times(self, hour12, minute, ampm, tz, now, days_ahead):
        # Independent 12h -> 24h table, not the function's own branch.
        hour24 = {("am", 12): 0, ("pm", 12): 12}.get((ampm, hour12), hour12 + (12 if ampm == "pm" else 0))
        d = (now + timedelta(days=days_ahead)).date()
        date_text = f"{d.month}/{d.day}/{d.year}"
        props = _props(time_pattern=TIME_PATTERN, date_pattern=DATE_PATTERN, timezone=tz)
        as12 = generate_custom_dummy_programs(1, f"X {hour12}:{minute:02d}{ampm} {date_text}", now, 1, props)
        as24 = generate_custom_dummy_programs(1, f"X {hour24}:{minute:02d} {date_text}", now, 1, props)
        self.assertEqual(
            [(p["start_time"], p["end_time"]) for p in as12],
            [(p["start_time"], p["end_time"]) for p in as24],
        )
        self.assertTrue(as12)
