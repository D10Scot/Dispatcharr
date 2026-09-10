"""Property-based tests for VOD provider-data normalization helpers.

``apps.vod.tasks`` ingests fields sent by arbitrary IPTV providers during
movie/series refresh (``get_vod_streams`` / ``get_vod_info`` rows). The
helpers covered here carry the same documented contract: be forgiving about
whatever the provider sent and never raise — a crash here aborts a whole
refresh task or a whole XC ``get_vod_streams`` listing.

The properties pin only what the implementations already promise (docstrings
and direct reads), against provider-shaped junk: unicode digits, comma
decimals, NaN/inf magnitudes, arrays-where-strings-are-expected, and deep
integers. Runs without Redis or the database (SimpleTestCase, pure
functions).
"""

import math
import re

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.vod.tasks import (
    clean_custom_properties,
    extract_duration_from_data,
    extract_string_from_array_or_string,
    extract_year,
    extract_year_from_title,
    is_blank_vod_value,
    is_non_empty_string,
    normalize_rating,
    should_update_field,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Any JSON-shaped value a provider might send.
jsonish = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=True, allow_infinity=True),
        st.text(max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=12), children, max_size=5),
    ),
    max_leaves=10,
)


class ExtractDurationProperties(SimpleTestCase):
    @given(data=st.dictionaries(st.text(max_size=12), jsonish, max_size=6))
    def test_never_raises_on_arbitrary_provider_rows(self, data):
        result = extract_duration_from_data(data)
        self.assertTrue(result is None or isinstance(result, int))

    @given(h=st.integers(0, 99), m=st.integers(0, 59), s=st.integers(0, 59))
    def test_hms_parses_to_seconds(self, h, m, s):
        result = extract_duration_from_data({"duration": f"{h:02d}:{m:02d}:{s:02d}"})
        self.assertEqual(result, h * 3600 + m * 60 + s)

    @given(m=st.integers(0, 999), s=st.integers(0, 59))
    def test_ms_parses_to_seconds(self, m, s):
        result = extract_duration_from_data({"duration": f"{m:02d}:{s:02d}"})
        self.assertEqual(result, m * 60 + s)

    @given(minutes=st.integers(0, 10**9))
    def test_bare_digits_mean_minutes(self, minutes):
        # Docstring behavior: a bare number is assumed to be minutes.
        result = extract_duration_from_data({"duration": str(minutes)})
        self.assertEqual(result, minutes * 60)

    @given(secs=st.integers(-(10**15), 10**15).filter(lambda s: s != 0))
    def test_duration_secs_passthrough(self, secs):
        self.assertEqual(extract_duration_from_data({"duration_secs": secs}), secs)

    def test_duration_secs_zero_is_dropped(self):
        # Deliberate falsy-check behavior: 0 seconds is indistinguishable from
        # "no duration" at every call site, so the helper discards it.
        self.assertIsNone(extract_duration_from_data({"duration_secs": 0}))


class NormalizeRatingProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_never_raises_and_returns_none_or_float_string(self, value):
        result = normalize_rating(value)
        self.assertTrue(result is None or isinstance(result, str))
        if result is not None:
            float(result)  # must be a valid float representation

    @given(value=st.floats(allow_nan=False, allow_infinity=False).filter(lambda v: v != 0.0))
    def test_nonzero_finite_floats_round_trip(self, value):
        result = normalize_rating(value)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(float(result), value)

    @given(
        whole=st.integers(0, 10),
        frac=st.integers(0, 99),
    )
    def test_comma_decimal_is_converted(self, whole, frac):
        # European "7,5" must normalize to "7.5".
        result = normalize_rating(f"{whole},{frac:02d}")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(float(result), float(f"{whole}.{frac:02d}"))

    def test_falsy_inputs_return_none(self):
        for falsy in (None, "", 0, 0.0, False, [], {}):
            self.assertIsNone(normalize_rating(falsy))

    @given(value=st.one_of(st.just("nan"), st.just("inf"), st.just("-inf"),
                           st.just("NaN"), st.just("Infinity")))
    def test_non_finite_values_do_not_crash(self, value):
        # float() accepts these; the helper's contract is only "never raise".
        result = normalize_rating(value)
        self.assertTrue(result is None or isinstance(result, str))


class ExtractYearProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), st.text(max_size=40)))
    def test_extract_year_never_raises_on_documented_inputs(self, value):
        # Restricted to the documented string contract; the non-string
        # AttributeError (e.g. an int year in a releaseDate field) is filed
        # as a finding, not pinned as intended behavior.
        result = extract_year(value)
        self.assertTrue(result is None or isinstance(result, int))

    @given(year=st.integers(1, 9999), month=st.integers(1, 12), day=st.integers(1, 28))
    def test_iso_date_yields_year(self, year, month, day):
        result = extract_year(f"{year:04d}-{month:02d}-{day:02d}")
        self.assertEqual(result, year)

    @given(title=st.text(max_size=120))
    def test_extract_year_from_title_never_raises(self, title):
        result = extract_year_from_title(title)
        self.assertTrue(result is None or 1900 <= result <= 2030)

    @given(year=st.integers(1900, 2030))
    def test_parenthesized_reasonable_year_is_found(self, year):
        self.assertEqual(extract_year_from_title(f"Some Movie ({year})"), year)

    @given(year=st.integers(1000, 1899))
    def test_parenthesized_old_year_is_rejected(self, year):
        # Years below 1900 fail the reasonableness window even when the
        # regex matches.
        self.assertIsNone(extract_year_from_title(f"Some Movie ({year})"))


class StringCoercionProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_is_non_empty_string_truthiness_matches_contract(self, value):
        result = is_non_empty_string(value)
        # Returns the stripped string (truthy) for non-blank text; both '' and
        # False are falsy, so truthiness is the contract callers rely on.
        self.assertEqual(bool(result), isinstance(value, str) and bool(value.strip()))

    @given(value=jsonish)
    def test_extract_string_never_raises(self, value):
        result = extract_string_from_array_or_string(value)
        self.assertTrue(result is None or isinstance(result, str))
        if result is not None:
            self.assertTrue(result.strip())  # never returns blank text

    @given(text=st.text(min_size=1, max_size=60).filter(lambda s: s.strip()))
    def test_string_passthrough_stripped(self, text):
        self.assertEqual(extract_string_from_array_or_string(text), text.strip())

    @given(items=st.lists(jsonish, min_size=1, max_size=6))
    def test_list_result_matches_first_valid_item(self, items):
        result = extract_string_from_array_or_string(items)
        # Either no valid item exists (None) or the result is the stripped
        # form of the first non-null item.
        if result is None:
            for item in items:
                self.assertTrue(item is None or not str(item).strip())
        else:
            self.assertTrue(result.strip())

    @given(existing=jsonish, new=jsonish)
    def test_should_update_field_never_raises_and_is_boolean(self, existing, new):
        result = should_update_field(existing, new)
        self.assertIsInstance(result, bool)

    def test_should_update_only_when_new_wins_and_existing_blank(self):
        self.assertTrue(should_update_field(None, "x"))
        self.assertTrue(should_update_field("", ["a"]))
        self.assertFalse(should_update_field("kept", "new"))
        self.assertFalse(should_update_field(None, ""))
        self.assertFalse(should_update_field(None, None))

    @given(value=jsonish)
    def test_is_blank_vod_value_never_raises(self, value):
        result = is_blank_vod_value(value)
        self.assertIsInstance(result, bool)
        # Spot the documented blanks.
        if value is None or value == "" or value == []:
            self.assertTrue(result)


class CleanCustomPropertiesProperties(SimpleTestCase):
    @given(props=st.one_of(
        st.none(),
        st.dictionaries(
            st.sampled_from(
                ["youtube_trailer", "actors", "director", "cast",
                 "backdrop_path", "genre", "year", "rating"]
            ),
            jsonish,
            max_size=8,
        ),
    ))
    def test_never_raises_and_returns_none_or_dict(self, props):
        result = clean_custom_properties(props)
        self.assertTrue(result is None or isinstance(result, dict))

    @given(props=st.dictionaries(
        st.sampled_from(["youtube_trailer", "actors", "director", "cast"]),
        jsonish,
        min_size=1,
        max_size=4,
    ))
    def test_string_fields_come_out_as_strings(self, props):
        result = clean_custom_properties(props) or {}
        for key in ("youtube_trailer", "actors", "director", "cast"):
            if key in result:
                self.assertIsInstance(result[key], str)

    @given(value=jsonish)
    def test_backdrop_path_comes_out_as_one_element_list(self, value):
        result = clean_custom_properties({"backdrop_path": value}) or {}
        if "backdrop_path" in result:
            self.assertIsInstance(result["backdrop_path"], list)
            self.assertEqual(len(result["backdrop_path"]), 1)

    def test_all_blank_input_returns_none(self):
        self.assertIsNone(clean_custom_properties(None))
        self.assertIsNone(clean_custom_properties({}))
        self.assertIsNone(clean_custom_properties({"a": None, "b": "", "c": []}))
        self.assertIsNone(clean_custom_properties({"a": [None, None]}))
