"""Property-based tests for the VOD provider-data normalisation helpers.

``apps/vod/tasks.py`` feeds these helpers fields from arbitrary IPTV provider JSON during
movie and series refresh. JSON has no schema, and XC panels are inconsistent about types:
a year may arrive as ``2011`` rather than ``"2011"``. So the properties draw provider values
from every JSON shape unless a comment says why a narrower domain is the real one.

Surfaces (``file:line`` at a54b09a9):

- ``extract_duration_from_data`` (``:1165``), ``normalize_rating`` (``:1193``),
  ``extract_year`` (``:1220``), ``extract_year_from_title`` (``:1230``) and ``parse_date``
  (``:1307``);
- ``is_non_empty_string`` (``:2106``), ``extract_string_from_array_or_string`` (``:2114``),
  ``clean_custom_properties`` (``:2132``), ``should_update_field`` (``:2163``) and
  ``is_blank_vod_value`` (``:2177``).

Issues: #243, and #92 (``parse_date``). ``extract_year``'s JSON-wide domain is the widening
#242 asked for once its fix (plan C, PR C-6) landed.
"""

import math
import string
from datetime import date, datetime

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.vod.tasks import (
    clean_custom_properties,
    extract_duration_from_data,
    extract_string_from_array_or_string,
    extract_year,
    extract_year_from_title,
    is_blank_vod_value,
    is_non_empty_string,
    normalize_rating,
    parse_date,
    should_update_field,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Any value json.loads can produce. Integers are bounded because json.loads itself refuses an
# int over sys.get_int_max_str_digits() digits, so a larger one never reaches these helpers.
json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=30),
)
jsonish = st.recursive(
    json_scalar,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=12), children, max_size=5),
    ),
    max_leaves=10,
)


def _has_text(value):
    """A provider value 'carries text': a non-blank string, or a list with an item whose text
    form is non-blank. Written out from the docstrings, independently of the helpers."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(item is not None and str(item).strip() for item in value)
    return False


class ExtractDurationProperties(SimpleTestCase):
    # Plan I finding F-6 (not filed at a54b09a9): a non-integer ``duration_secs`` ("1.5", "abc", a list,
    # inf, nan) raises at apps/vod/tasks.py:1171, and a ``duration`` made of isdigit()-but-not-decimal
    # characters ("²") raises at :1176, both outside any try. The per-movie try at :434/:545 drops
    # that one movie. Until that is fixed, the never-raises domain below is integer
    # ``duration_secs`` and ``duration`` text without Unicode category No (where "²" lives).
    @given(
        secs=st.one_of(st.none(), st.integers(min_value=-(10**12), max_value=10**12),
                       st.integers(min_value=0, max_value=10**12).map(str)),
        duration=st.one_of(
            st.none(),
            st.integers(min_value=0, max_value=10**6),
            st.text(st.characters(exclude_categories=("No", "Cs")), max_size=12),
            st.text("0123456789:-", max_size=10),
        ),
    )
    def test_extract_duration_never_raises_on_integer_seconds_or_duration_text(self, secs, duration):
        row = {k: v for k, v in (("duration_secs", secs), ("duration", duration)) if v is not None}
        result = extract_duration_from_data(row)
        self.assertTrue(result is None or (isinstance(result, int) and not isinstance(result, bool)))

    @given(secs=st.integers(min_value=1, max_value=10**9), duration=st.text(max_size=12))
    def test_extract_duration_prefers_a_non_zero_duration_secs(self, secs, duration):
        self.assertEqual(extract_duration_from_data({"duration_secs": secs, "duration": duration}), secs)
        self.assertEqual(extract_duration_from_data({"duration_secs": str(secs)}), secs)

    @given(minutes=st.integers(min_value=1, max_value=10**4))
    def test_extract_duration_zero_seconds_falls_through_to_duration(self, minutes):
        # duration_secs is a truthiness check: 0 means "absent", so ``duration`` decides.
        self.assertEqual(
            extract_duration_from_data({"duration_secs": 0, "duration": str(minutes)}), minutes * 60
        )

    @given(h=st.integers(0, 99), m=st.integers(0, 59), s=st.integers(0, 59), pad=st.booleans())
    def test_extract_duration_hms_and_ms_parse_to_seconds(self, h, m, s, pad):
        fmt = "{:02d}" if pad else "{}"
        hms = ":".join(fmt.format(v) for v in (h, m, s))
        ms = ":".join(fmt.format(v) for v in (m, s))
        self.assertEqual(extract_duration_from_data({"duration": hms}), h * 3600 + m * 60 + s)
        self.assertEqual(extract_duration_from_data({"duration": ms}), m * 60 + s)

    @given(minutes=st.integers(min_value=0, max_value=10**6), as_int=st.booleans())
    def test_extract_duration_bare_number_means_minutes(self, minutes, as_int):
        value = minutes if as_int else str(minutes)
        result = extract_duration_from_data({"duration": value})
        if value == 0:
            self.assertIsNone(result)  # an int 0 is falsy: there is no duration at all
        else:
            self.assertEqual(result, minutes * 60)  # "0" is truthy text and yields 0


class NormalizeRatingProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_normalize_rating_never_raises_and_returns_none_or_a_float_string(self, value):
        result = normalize_rating(value)
        if result is not None:
            self.assertIsInstance(result, str)
            float(result)
        if not value:
            self.assertIsNone(result)

    @given(value=st.floats(allow_nan=False, allow_infinity=False).filter(lambda v: v != 0.0),
           as_text=st.booleans())
    def test_normalize_rating_round_trips_non_zero_finite_floats_exactly(self, value, as_text):
        result = normalize_rating(repr(value) if as_text else value)
        self.assertEqual(float(result), value)

    @given(whole=st.integers(0, 10), frac=st.integers(0, 999))
    def test_normalize_rating_reads_a_decimal_comma(self, whole, frac):
        self.assertEqual(normalize_rating(f" {whole},{frac} "), str(float(f"{whole}.{frac}")))


class ExtractYearProperties(SimpleTestCase):
    @given(value=jsonish)
    # #242: a truthy non-string provider value raised AttributeError from date_string.split.
    @example(value=1)  # #242's shrunk counterexample
    @example(value=2011)  # "releaseDate": 2011, as XC panels send it
    @example(value=[2011])
    @example(value=2011.5)
    @example(value=True)
    def test_extract_year_never_raises_on_any_json_value(self, value):
        result = extract_year(value)
        self.assertTrue(result is None or (isinstance(result, int) and not isinstance(result, bool)))

    # From 1: an int 0 is falsy and short-circuits to None, while the text "0" yields 0. That
    # asymmetry is the helper's own ``if not date_string`` guard and predates #242.
    @given(year=st.integers(min_value=1, max_value=10**6))
    @example(year=1)  # #242
    @example(year=2011)  # #242
    def test_extract_year_reads_an_integer_year_like_its_string_form(self, year):
        self.assertEqual(extract_year(year), year)
        self.assertEqual(extract_year(year), extract_year(str(year)))

    def test_extract_year_c6_expected_values(self):
        # Plan C, PR C-6's table: the int year is kept, other non-string shapes yield no year.
        for value, expected in ((1, 1), (2011, 2011), ([2011], None), (2011.5, None), (True, None)):
            with self.subTest(value=value):
                self.assertEqual(extract_year(value), expected)

    @given(year=st.integers(1, 9999), month=st.integers(1, 12), day=st.integers(1, 28), tail=st.text(max_size=8))
    def test_extract_year_takes_the_year_of_an_iso_date(self, year, month, day, tail):
        self.assertEqual(extract_year(f"{year:04d}-{month:02d}-{day:02d}{tail}"), year)


class ExtractYearFromTitleProperties(SimpleTestCase):
    @given(title=st.one_of(st.none(), st.text(max_size=80)))
    def test_extract_year_from_title_never_raises_and_stays_in_the_window(self, title):
        result = extract_year_from_title(title)
        self.assertTrue(result is None or 1900 <= result <= 2030)

    @given(
        name=st.text(string.ascii_letters + " ", min_size=1, max_size=20).filter(lambda s: s.strip()),
        year=st.integers(1900, 2030),
        form=st.sampled_from(["{n} ({y})", "{n} - {y}", "{n} {y}"]),
    )
    def test_extract_year_from_title_finds_each_documented_form(self, name, year, form):
        self.assertEqual(extract_year_from_title(form.format(n=name.strip(), y=year)), year)

    @given(year=st.one_of(st.integers(1000, 1899), st.integers(2031, 9999)),
           form=st.sampled_from(["Film ({y})", "Film - {y}", "Film {y}"]))
    def test_extract_year_from_title_rejects_years_outside_1900_to_2030(self, year, form):
        self.assertIsNone(extract_year_from_title(form.format(y=year)))


class ParseDateProperties(SimpleTestCase):
    # Domain is ``str``: the only caller, extract_date_from_data (:1292), passes a value only
    # after isinstance(date_value, str), inside a broad try.
    @given(value=st.one_of(st.text(max_size=40), st.text("0123456789-/:TZ. +", max_size=30)))
    def test_parse_date_never_raises_on_text(self, value):
        result = parse_date(value)
        self.assertTrue(result is None or isinstance(result, datetime))

    @given(d=st.dates())
    def test_parse_date_parses_every_canonical_date(self, d):
        self.assertEqual(parse_date(d.isoformat()), datetime(d.year, d.month, d.day))

    @given(dt=st.datetimes())
    def test_parse_date_round_trips_isoformat(self, dt):
        self.assertEqual(parse_date(dt.isoformat()), dt)

    @given(year=st.integers(1, 9999), month=st.integers(1, 12), day=st.integers(29, 31))
    def test_parse_date_returns_none_for_an_impossible_calendar_date(self, year, month, day):
        try:
            date(year, month, day)
        except ValueError:
            self.assertIsNone(parse_date(f"{year:04d}-{month:02d}-{day:02d}"))


class StringFieldProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_is_non_empty_string_truthiness_is_non_blank_str(self, value):
        self.assertEqual(bool(is_non_empty_string(value)), isinstance(value, str) and bool(value.strip()))

    @given(value=jsonish)
    @example(value=[None, "  ", 0])  # the 0 is text "0": non-blank
    @example(value=[{"a": 1}])
    def test_extract_string_is_the_first_item_with_text_stripped(self, value):
        result = extract_string_from_array_or_string(value)
        if isinstance(value, str):
            expected = value.strip() or None
        elif isinstance(value, list):
            expected = next(
                (str(i).strip() for i in value if i is not None and str(i).strip()), None
            )
        else:
            expected = None
        self.assertEqual(result, expected)

    @given(existing=jsonish, new=jsonish)
    @example(existing="kept", new="new")
    @example(existing=None, new="   ")
    @example(existing=[None, ""], new=["x"])
    def test_should_update_field_iff_new_has_text_and_existing_has_none(self, existing, new):
        self.assertIs(should_update_field(existing, new), _has_text(new) and not _has_text(existing))

    @given(value=jsonish)
    @example(value=())  # a tuple is not a list: not blank
    @example(value=[None, ""])
    @example(value=0)
    def test_is_blank_vod_value_is_none_empty_or_a_list_of_only_blanks(self, value):
        expected = value is None or (isinstance(value, str) and value == "") or (
            isinstance(value, list) and all(i is None or (isinstance(i, str) and i == "") for i in value)
        )
        self.assertIs(is_blank_vod_value(value), expected)


_STRING_FIELDS = ("youtube_trailer", "actors", "director", "cast")


class CleanCustomPropertiesProperties(SimpleTestCase):
    # Domain is a dict or a falsy value: every caller passes a provider row or ``info`` already
    # normalised to a dict (apps/vod/tasks.py:2233-2240, :2334, :2358-2359).
    @given(
        props=st.one_of(
            st.none(),
            st.dictionaries(
                st.one_of(st.sampled_from(_STRING_FIELDS + ("backdrop_path", "genre", "rating")),
                          st.text(max_size=8)),
                jsonish,
                max_size=8,
            ),
        )
    )
    @example(props={"actors": ["", None, " Ann "], "backdrop_path": [None, " http://x/b.jpg "]})
    @example(props={"a": None, "b": "", "c": [], "d": [None, None]})
    def test_clean_custom_properties_keeps_only_meaningful_values(self, props):
        result = clean_custom_properties(props)
        if result is None:
            result = {}
        else:
            self.assertTrue(result)  # an empty cleaning is None, never {}
        for key, value in (props or {}).items():
            if key in _STRING_FIELDS:
                if _has_text(value):
                    self.assertEqual(result[key], extract_string_from_array_or_string(value))
                    self.assertEqual(result[key], result[key].strip())
                else:
                    self.assertNotIn(key, result)
            elif key == "backdrop_path":
                if _has_text(value):
                    self.assertEqual(result[key], [extract_string_from_array_or_string(value)])
                else:
                    self.assertNotIn(key, result)
            elif value is None or value == "" or value == [] or (
                isinstance(value, list) and all(i is None for i in value)
            ):
                self.assertNotIn(key, result)
            else:
                self.assertIs(result[key], value)
        self.assertLessEqual(set(result), set(props or {}))
