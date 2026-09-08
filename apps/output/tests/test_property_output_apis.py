"""Property-based tests for output-API pure helpers (EPG, artwork, formatting).

These cover the parsing/formatting surfaces of the ``output-apis`` domain
(``apps.output``, ``apps.vod`` image helpers, ``apps.channels.utils``) that
consume provider- or user-controlled values:

* ``apps.output.epg._programme_overlaps_export_window`` — window predicate that
  decides whether a programme survives the EPG export's lookback/cutoff.
* ``apps.output.epg._ceil_to_half_hour`` — rounds a datetime up to the next
  :00/:30 boundary (used when a custom dummy event falls outside the window).
* ``apps.output.epg.generate_custom_dummy_programs`` — parses provider channel
  names with an admin-configured regex and must never raise on matched input.
* ``apps.channels.utils.format_channel_number`` — display formatting for the
  FloatField ``channel_number``; feeds M3U, EPG and HDHR lineup output.
* ``apps.output.views.format_duration_hms`` — HH:MM:SS formatting for XC
  ``duration`` fields.
* ``apps.vod.image_proxy`` artwork extractors — shape-tolerant over arbitrary
  ``custom_properties`` JSON from providers.

All run under SimpleTestCase with no DB and no Redis. CI-deterministic profile
(derandomize, deadline=None) matches the live_proxy property tests.
"""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.channels.utils import format_channel_number
from apps.output.epg import (
    _ceil_to_half_hour,
    _programme_overlaps_export_window,
    generate_custom_dummy_programs,
)
from apps.output.views import format_duration_hms
from apps.vod.image_proxy import (
    _as_backdrop_list,
    get_relation_artwork,
    is_proxyable_image_url,
    prefer_relation_artwork,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

UTC = timezone.utc
# Stay clear of datetime.max so ``_ceil_to_half_hour``'s internal
# ``+ timedelta(minutes=30)`` cannot overflow (that pre-existing overflow is a
# known defect, filed separately — not what these properties assert).
SAFE_DT = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(9999, 1, 1),
    timezones=st.just(UTC),
)


class ProgrammeWindowProperties(SimpleTestCase):
    """The export-window predicate is a pure total function of four datetimes."""

    @given(
        start=SAFE_DT,
        end=SAFE_DT,
        lookback=SAFE_DT,
        cutoff=st.one_of(st.none(), SAFE_DT),
    )
    def test_never_raises_and_matches_spec(self, start, end, lookback, cutoff):
        result = _programme_overlaps_export_window(start, end, lookback, cutoff)
        self.assertIsInstance(result, bool)
        # The function is exactly: overlap iff end >= lookback and
        # (no cutoff or start < cutoff). Pin the composition so a future
        # refactor cannot silently invert one arm.
        expected = (end >= lookback) and (cutoff is None or start < cutoff)
        self.assertEqual(result, expected)

    @given(start=SAFE_DT, delta1=st.integers(0, 10**6), delta2=st.integers(0, 10**6))
    def test_programme_fully_inside_window_always_overlaps(self, start, delta1, delta2):
        lookback = start - timedelta(seconds=delta1)
        cutoff = start + timedelta(seconds=delta2 + 1)
        self.assertTrue(
            _programme_overlaps_export_window(start, start + timedelta(hours=1), lookback, cutoff)
        )


class CeilToHalfHourProperties(SimpleTestCase):
    """Rounding up to :00/:30 lands on a boundary and never moves backwards."""

    @given(dt=SAFE_DT)
    def test_lands_on_half_hour_boundary(self, dt):
        out = _ceil_to_half_hour(dt)
        self.assertEqual(out.minute % 30, 0)
        self.assertEqual(out.second, 0)
        self.assertEqual(out.microsecond, 0)

    @given(dt=SAFE_DT)
    def test_result_is_the_least_boundary_not_before_input(self, dt):
        out = _ceil_to_half_hour(dt)
        self.assertGreaterEqual(out, dt.replace(microsecond=0))
        # No earlier boundary may also satisfy >= input.
        prev = out - timedelta(minutes=30)
        self.assertLess(prev, dt.replace(microsecond=0))


class CustomDummyEpgProperties(SimpleTestCase):
    """generate_custom_dummy_programs parses provider-controlled channel names.

    A channel name that matches the admin-configured title/time patterns must
    never raise: whatever digits the provider put in the time slot, the export
    either produces programs or falls back — an exception here aborts the whole
    streaming /output/epg response mid-body.
    """

    # In-range hours/minutes: this is the invariant the implementation *does*
    # promise today. Out-of-range captures (minute=99, day=Feb 31, …) currently
    # crash; those falsified cases are filed as issues, not pinned here.
    @given(
        hour=st.integers(0, 23),
        minute=st.integers(0, 59),
        trailing=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            max_size=20,
        ),
    )
    def test_valid_time_capture_never_raises(self, hour, minute, trailing):
        props = {
            "title_pattern": r"(?<title>.*)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "program_duration": 60,
        }
        now = datetime.now(UTC)
        name = f"Event {hour}:{minute:02d} {trailing}"
        result = generate_custom_dummy_programs(1, name, now, 1, props)
        # Either programs or None (no match) — never an exception, and every
        # emitted programme is well-formed.
        if result is None:
            return
        for prog in result:
            self.assertGreater(prog["end_time"], prog["start_time"])
            self.assertEqual(prog["channel_id"], 1)

    @given(
        month=st.integers(1, 12),
        day=st.integers(1, 28),
        hour=st.integers(0, 23),
        minute=st.integers(0, 59),
    )
    def test_valid_datetime_capture_never_raises(self, month, day, hour, minute):
        props = {
            "title_pattern": r"(?<title>.*)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "date_pattern": r"(?<month>\d+)/(?<day>\d+)",
            "program_duration": 60,
        }
        now = datetime.now(UTC)
        name = f"Game {hour}:{minute:02d} on {month}/{day}"
        result = generate_custom_dummy_programs(1, name, now, 1, props)
        if result is None:
            return
        for prog in result:
            self.assertGreater(prog["end_time"], prog["start_time"])

    @given(
        hour=st.integers(0, 23),
        minute=st.integers(0, 59),
        duration=st.integers(1, 24 * 60),
    )
    def test_am_pm_conversion_matches_24h_clock(self, hour, minute, duration):
        """12-hour input must land on the same wall-clock instant as 24-hour.

        The parser converts 12h→24h (12am→0, 12pm→12, Npm→N+12). Feeding the
        converted 24-hour string without am/pm must yield the same event times
        as the 12-hour string with am/pm — otherwise the conversion is wrong.
        """
        ampm = "am" if hour < 12 else "pm"
        hour_12 = hour % 12 or 12
        props12 = {
            "title_pattern": r"(?<title>.*)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)\s*(?<ampm>[aApP][mM])",
            "program_duration": duration,
        }
        props24 = {
            "title_pattern": r"(?<title>.*)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "program_duration": duration,
        }
        now = datetime.now(UTC)
        r12 = generate_custom_dummy_programs(1, f"S {hour_12}:{minute:02d} {ampm}", now, 1, props12)
        r24 = generate_custom_dummy_programs(1, f"S {hour}:{minute:02d}", now, 1, props24)
        self.assertEqual(r12 is None, r24 is None)
        if r12 is None:
            return
        starts12 = sorted(p["start_time"] for p in r12)
        starts24 = sorted(p["start_time"] for p in r24)
        self.assertEqual(starts12, starts24)


class FormatChannelNumberProperties(SimpleTestCase):
    """Whole-valued floats render as int; fractional and None pass through."""

    @given(value=st.floats(allow_nan=False, allow_infinity=False))
    def test_finite_floats_never_raise(self, value):
        out = format_channel_number(value)
        if float(value).is_integer() and abs(value) < 2**63:
            self.assertIsInstance(out, int)
            self.assertEqual(out, int(value))

    @given(value=st.integers(-10**6, 10**6))
    def test_whole_float_renders_as_int(self, value):
        self.assertEqual(format_channel_number(float(value)), value)

    @given(empty=st.text(max_size=10))
    def test_none_returns_empty_marker(self, empty):
        self.assertEqual(format_channel_number(None, empty=empty), empty)


class FormatDurationProperties(SimpleTestCase):
    """format_duration_hms produces zero-padded HH:MM:SS with consistent carry."""

    @given(seconds=st.integers(0, 10**7))
    def test_nonnegative_seconds_format(self, seconds):
        out = format_duration_hms(seconds)
        h, m, s = out.split(":")
        self.assertEqual(int(s), seconds % 60)
        self.assertEqual(int(m), (seconds % 3600) // 60)
        self.assertEqual(int(h), seconds // 3600)
        self.assertEqual(len(m), 2)
        self.assertEqual(len(s), 2)

    @given(value=st.one_of(st.none(), st.sampled_from([0, "", False])))
    def test_falsy_input_is_zero(self, value):
        self.assertEqual(format_duration_hms(value), "00:00:00")


class VodArtworkProperties(SimpleTestCase):
    """Artwork extractors are total over arbitrary custom_properties shapes."""

    @given(props=st.one_of(st.none(), st.integers(), st.text(max_size=20), st.lists(st.text(max_size=5), max_size=3), st.dictionaries(st.text(max_size=5), st.text(max_size=5), max_size=5)))
    def test_get_relation_artwork_never_raises(self, props):
        out = get_relation_artwork(props)
        self.assertEqual(set(out.keys()), {"movie_image", "backdrop_path"})
        self.assertIsInstance(out["movie_image"], str)
        self.assertIsInstance(out["backdrop_path"], list)

    @given(
        rel=st.one_of(st.none(), st.dictionaries(st.sampled_from(["movie_image", "cover_big", "stream_icon", "cover", "backdrop_path", "info", "detailed_info", "basic_data"]), st.one_of(st.text(max_size=15), st.lists(st.text(max_size=10), max_size=3), st.none()), max_size=6)),
        obj=st.one_of(st.none(), st.dictionaries(st.sampled_from(["movie_image", "backdrop_path"]), st.one_of(st.text(max_size=15), st.lists(st.text(max_size=10), max_size=3)), max_size=2)),
    )
    def test_prefer_relation_artwork_never_raises(self, rel, obj):
        out = prefer_relation_artwork(rel, obj)
        self.assertIsInstance(out["movie_image"], str)
        self.assertIsInstance(out["backdrop_path"], list)

    @given(value=st.one_of(st.none(), st.text(max_size=30), st.integers(), st.lists(st.text(max_size=5), max_size=3), st.tuples(st.text(max_size=5))))
    def test_as_backdrop_list_shape(self, value):
        out = _as_backdrop_list(value)
        self.assertIsInstance(out, list)
        if isinstance(value, str) and value:
            self.assertEqual(out, [value])
        elif isinstance(value, (list, tuple)):
            self.assertEqual(out, list(value))
        else:
            self.assertEqual(out, [])

    @given(url=st.one_of(st.none(), st.text(max_size=40), st.integers()))
    def test_is_proxyable_image_url_only_accepts_http_or_data(self, url):
        out = is_proxyable_image_url(url)
        self.assertIsInstance(out, bool)
        if out:
            self.assertTrue(
                url.startswith(("http://", "https://", "/data")),
                f"non-allowlisted URL proxied: {url!r}",
            )
        # Anything not a string is rejected outright.
        if not isinstance(url, str) or url is None:
            self.assertFalse(out)


class XcDurationProperty(SimpleTestCase):
    """Cross-check format_duration_hms against the HH:MM:SS contract."""

    @given(h=st.integers(0, 99), m=st.integers(0, 59), s=st.integers(0, 59))
    def test_round_trip(self, h, m, s):
        total = h * 3600 + m * 60 + s
        self.assertEqual(format_duration_hms(total), f"{h:02}:{m:02}:{s:02}")
