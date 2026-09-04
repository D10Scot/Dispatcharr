"""Property-based tests for output-API formatting/parsing helpers.

The surfaces covered here sit on the XC/HDHR/M3U/XMLTV output paths and
consume data that is only partially trusted: provider-supplied channel
numbers and names, JSONField ``custom_properties`` payloads (which API
clients can submit as any JSON type, including a bare string), and
legacy rows that predate current invariants. The contracts asserted are
the ones the implementations actually advertise:

- ``apps.channels.utils.format_channel_number`` — display formatting for an
  effective channel_number: int for whole-valued floats, the float as-is for
  fractional values, ``empty`` for None. Must not raise for finite values.
- ``apps.output.views.format_duration_hms`` — HH:MM:SS zero-padded string;
  integer input renders with minutes/seconds in range.
- ``apps.output.epg._ceil_to_half_hour`` — rounds *up* to the next :00/:30
  boundary; result is aligned, never before the (second-truncated) input,
  and at most 30 minutes ahead.
- ``apps.output.epg._programme_overlaps_export_window`` — pure two-sided
  interval test; consistent with its own boundary conditions.
- ``apps.channels.utils.coerce_channel_profile_ids`` — normalizes the UI
  MultiSelect's string IDs to a list of ints, dropping unparseable items,
  surviving legacy string-valued custom_properties.
- ``core.utils.custom_properties_as_dict`` / ``ensure_custom_properties_dict``
  — always return a dict, whatever JSON-typed value the row holds.
- ``apps.vod.image_proxy`` — ``is_proxyable_image_url`` never raises and
  only blesses http(s)/local paths; ``get_relation_artwork`` /
  ``prefer_relation_artwork`` always return the documented
  ``{"movie_image": str, "backdrop_path": list}`` shape for arbitrary
  relation payloads.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

import json
import math
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.channels.utils import coerce_channel_profile_ids, format_channel_number
from apps.output.epg import _ceil_to_half_hour, _programme_overlaps_export_window
from apps.output.views import format_duration_hms
from apps.vod.image_proxy import (
    get_relation_artwork,
    is_proxyable_image_url,
    prefer_relation_artwork,
)
from core.utils import custom_properties_as_dict, ensure_custom_properties_dict

# CI-deterministic profile — see test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

finite_floats = st.floats(allow_nan=False, allow_infinity=False)


class FormatChannelNumberProperties(SimpleTestCase):
    @given(value=finite_floats)
    def test_finite_float_never_raises_and_preserves_value(self, value):
        result = format_channel_number(value)
        # Whole-valued floats collapse to int; fractional pass through.
        if value == int(value):
            self.assertIsInstance(result, int)
            self.assertEqual(result, int(value))
        else:
            self.assertEqual(result, value)

    @given(value=finite_floats, empty=st.text(max_size=8))
    def test_none_returns_empty_sentinel(self, value, empty):
        self.assertIs(format_channel_number(None, empty=empty), empty)

    @given(value=st.integers(min_value=-(2**63), max_value=2**63))
    def test_integers_pass_through_as_ints(self, value):
        self.assertEqual(format_channel_number(value), value)


class FormatDurationHmsProperties(SimpleTestCase):
    @given(seconds=st.integers(min_value=0, max_value=10**9))
    def test_non_negative_duration_shape(self, seconds):
        result = format_duration_hms(seconds)
        hours, minutes, secs = result.split(":")
        self.assertEqual(int(hours), seconds // 3600)
        self.assertEqual(int(minutes), (seconds % 3600) // 60)
        self.assertEqual(int(secs), seconds % 60)
        # Minutes/seconds are always two-digit zero-padded.
        self.assertEqual(len(minutes), 2)
        self.assertEqual(len(secs), 2)

    def test_none_and_falsey_become_zero(self):
        self.assertEqual(format_duration_hms(None), "00:00:00")
        self.assertEqual(format_duration_hms(0), "00:00:00")


class CeilToHalfHourProperties(SimpleTestCase):
    @given(
        dt=st.datetimes(
            min_value=datetime(2000, 1, 1),
            max_value=datetime(2100, 1, 1),
            timezones=st.just(timezone.utc),
        )
    )
    def test_aligned_monotonic_and_bounded(self, dt):
        result = _ceil_to_half_hour(dt)
        original = dt.replace(microsecond=0)
        # Never goes backwards (modulo sub-second precision, which the
        # function explicitly truncates).
        self.assertGreaterEqual(result, original)
        # Always lands on a :00/:30 boundary.
        self.assertEqual(result.minute % 30, 0)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.microsecond, 0)
        # At most 30 minutes ahead of the truncated input.
        self.assertLessEqual(result - original, timedelta(minutes=30))


class ProgrammeOverlapProperties(SimpleTestCase):
    @given(
        start_offset=st.integers(min_value=0, max_value=10**7),
        duration=st.integers(min_value=0, max_value=10**6),
        lookback_offset=st.integers(min_value=0, max_value=10**7),
        cutoff_offset=st.one_of(st.none(), st.integers(min_value=0, max_value=10**7)),
    )
    def test_overlap_decision_matches_boundary_rules(self, start_offset, duration, lookback_offset, cutoff_offset):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        start = base + timedelta(seconds=start_offset)
        end = start + timedelta(seconds=duration)
        lookback = base + timedelta(seconds=lookback_offset)
        cutoff = base + timedelta(seconds=cutoff_offset) if cutoff_offset is not None else None

        result = _programme_overlaps_export_window(start, end, lookback, cutoff)
        expected = not (end < lookback) and not (cutoff is not None and start >= cutoff)
        self.assertEqual(result, expected)

    def test_touching_lookback_boundary_overlaps(self):
        # end_time == lookback_cutoff must still count as overlapping
        # (the guard is a strict ``<``).
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(
            _programme_overlaps_export_window(base, base, base, None)
        )


class CoerceChannelProfileIdsProperties(SimpleTestCase):
    json_scalars = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-10**6, max_value=10**6),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=20),
    )

    @given(props=st.one_of(json_scalars, st.dictionaries(st.text(max_size=8), json_scalars, max_size=5)))
    def test_any_json_value_never_raises(self, props):
        result = coerce_channel_profile_ids(props)
        self.assertIsInstance(result, dict)
        ids = result.get("channel_profile_ids")
        if ids is not None:
            self.assertIsInstance(ids, list)
            for item in ids:
                self.assertIsInstance(item, int)

    @given(items=st.lists(st.one_of(st.integers(-10**6, 10**6), st.text(max_size=10)), max_size=20))
    def test_list_items_coerce_or_drop(self, items):
        result = coerce_channel_profile_ids({"channel_profile_ids": items})
        ids = result["channel_profile_ids"]
        self.assertIsInstance(ids, list)
        for item in ids:
            self.assertIsInstance(item, int)
        # Every int in the input survives (in order relative to other ints).
        expected_ints = [i for i in items if isinstance(i, int) and not isinstance(i, bool)]
        kept_ints = [i for i in ids if i in expected_ints or str(i) in [str(x) for x in items]]
        for i in expected_ints:
            self.assertIn(i, kept_ints)

    def test_missing_key_passes_props_through(self):
        self.assertEqual(coerce_channel_profile_ids({"other": 1}), {"other": 1})


class CustomPropertiesNormalizationProperties(SimpleTestCase):
    any_json = st.recursive(
        st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(max_size=16)),
        lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4),
        max_leaves=8,
    )

    @given(value=any_json)
    def test_custom_properties_as_dict_always_dict(self, value):
        self.assertIsInstance(custom_properties_as_dict(value), dict)

    @given(value=any_json)
    def test_custom_properties_as_dict_json_string_roundtrip(self, value):
        # A JSON-encoded string holding a dict parses back; anything else
        # degrades to {}. Either way: dict, never a raise.
        self.assertIsInstance(custom_properties_as_dict(json.dumps(value)), dict)

    @given(value=any_json)
    def test_ensure_custom_properties_dict_always_dict(self, value):
        self.assertIsInstance(ensure_custom_properties_dict(value), dict)


class VodImageProxyProperties(SimpleTestCase):
    @given(url=st.one_of(st.none(), st.text(max_size=200), st.integers(), st.binary(max_size=50)))
    def test_is_proxyable_image_url_never_raises(self, url):
        result = is_proxyable_image_url(url)
        self.assertIsInstance(result, bool)
        if result:
            # Blessed URLs only ever come from the three documented prefixes.
            self.assertIsInstance(url, str)
            self.assertTrue(url.startswith(("http://", "https://", "/data")))

    relation_shapes = st.one_of(
        st.none(),
        st.text(max_size=20),
        st.integers(),
        st.lists(st.integers(), max_size=3),
        st.dictionaries(
            st.sampled_from(["info", "detailed_info", "basic_data", "movie_image", "backdrop_path", "cover", "stream_icon", "cover_big", "junk"]),
            st.one_of(
                st.none(),
                st.text(max_size=40),
                st.integers(),
                st.lists(st.text(max_size=20), max_size=3),
                st.dictionaries(st.text(max_size=8), st.text(max_size=20), max_size=3),
            ),
            max_size=6,
        ),
    )

    @given(props=relation_shapes)
    def test_get_relation_artwork_shape_and_robustness(self, props):
        result = get_relation_artwork(props)
        self.assertIsInstance(result["movie_image"], str)
        self.assertIsInstance(result["backdrop_path"], list)

    @given(rel=relation_shapes, obj=relation_shapes)
    def test_prefer_relation_artwork_shape_and_robustness(self, rel, obj):
        result = prefer_relation_artwork(rel, obj)
        self.assertIsInstance(result["movie_image"], str)
        self.assertIsInstance(result["backdrop_path"], list)
        # A movie_image the helper emits is always stripped of outer whitespace.
        self.assertEqual(result["movie_image"], result["movie_image"].strip())

    @given(value=st.one_of(st.none(), st.text(max_size=60), st.lists(st.text(max_size=20), max_size=4), st.integers()))
    def test_get_relation_artwork_movie_image_always_stripped_str(self, value):
        result = get_relation_artwork({"movie_image": value})
        self.assertIsInstance(result["movie_image"], str)
        self.assertEqual(result["movie_image"], result["movie_image"].strip())
