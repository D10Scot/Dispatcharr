"""Property tests for the pure formatting and normalisation helpers behind the output APIs.

Surfaces (``file:line`` at a54b09a9):

- ``format_duration_hms`` (``apps/output/views.py:1778``): renders a provider's
  ``duration_secs`` into XC ``get_series_info`` (``apps/output/views.py:1494``).
- ``_encode_chunk`` / ``_decode_chunk`` (``apps/output/streaming_chunk_cache.py:44``, ``:36``):
  the leader stores encoded chunks and followers replay decoded ones, so a follower's
  M3U/XMLTV body must equal the leader's.
- ``format_channel_number`` (``apps/channels/utils.py:46``): the channel number in the
  M3U, the XMLTV and the HDHomeRun lineup.
- ``coerce_channel_profile_ids`` (``apps/channels/utils.py:22``): group-settings
  ``custom_properties`` in and out of the API.
- ``custom_properties_as_dict`` / ``ensure_custom_properties_dict`` (``core/utils.py:79``,
  ``:105``): the normaliser every ``custom_properties`` reader goes through.

Closes the formatting half of #92 (dups #210, #162).
"""

import json
import math
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.channels.utils import coerce_channel_profile_ids, format_channel_number
from apps.output.streaming_chunk_cache import _decode_chunk, _encode_chunk
from apps.output.views import format_duration_hms
from core.utils import custom_properties_as_dict, ensure_custom_properties_dict

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Values a JSONField can hold. Floats are finite: PostgreSQL jsonb rejects NaN and
# Infinity, and DRF's JSON parser refuses the NaN/Infinity tokens. One gap: json.loads
# reads the literal 1e999 as inf, and coerce_channel_profile_ids then raises
# OverflowError (plan I finding F-8), so finite floats are also that finding's exclusion.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(10**6), 10**6)
    | st.floats(allow_nan=False, allow_infinity=False, width=32) | st.text(max_size=10),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=6), children, max_size=4),
    max_leaves=12,
)
json_dicts = st.dictionaries(st.text(max_size=6), json_values, max_size=4)


class FormatDurationHmsProperties(SimpleTestCase):
    @given(seconds=st.integers(0, 10**7))
    @example(seconds=0)
    @example(seconds=59)
    @example(seconds=3600)
    @example(seconds=360000)  # 100 hours: the hour field widens past two digits
    def test_renders_zero_padded_fields_that_sum_back_to_the_input(self, seconds):
        text = format_duration_hms(seconds)
        hh, mm, ss = text.split(":")
        self.assertGreaterEqual(len(hh), 2)
        self.assertEqual((len(mm), len(ss)), (2, 2))
        self.assertTrue(0 <= int(mm) < 60 and 0 <= int(ss) < 60)
        self.assertEqual(int(hh) * 3600 + int(mm) * 60 + int(ss), seconds)

    @given(seconds=st.floats(0, 10**7, allow_nan=False))
    def test_float_input_renders_as_its_truncated_whole_seconds(self, seconds):
        self.assertEqual(format_duration_hms(seconds), format_duration_hms(int(seconds)))

    @given(falsy=st.sampled_from([None, 0, 0.0, "", False]))
    def test_falsy_input_is_zero(self, falsy):
        self.assertEqual(format_duration_hms(falsy), "00:00:00")


class ChunkCacheCodecProperties(SimpleTestCase):
    # st.text() excludes surrogates by default; chunks are built from text PostgreSQL
    # stored, and PostgreSQL cannot store a lone surrogate.
    @given(chunk=st.text(max_size=200))
    @example(chunk="<tv>é\U0001f4fa</tv>\n")
    def test_text_chunk_round_trips_exactly(self, chunk):
        encoded = _encode_chunk(chunk)
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(_decode_chunk(encoded), chunk)

    @given(chunk=st.binary(max_size=200))
    def test_bytes_chunk_is_stored_as_given(self, chunk):
        self.assertIs(_encode_chunk(chunk), chunk)

    @given(chunk=st.text(max_size=50))
    def test_decode_passes_text_and_none_through(self, chunk):
        self.assertIs(_decode_chunk(chunk), chunk)
        self.assertIsNone(_decode_chunk(None))


class FormatChannelNumberProperties(SimpleTestCase):
    # Finite values only. format_channel_number(nan) raises ValueError and inf raises
    # OverflowError; plan I finding F-7 traces how a provider can probably store either.
    @given(whole=st.integers(-(10**9), 10**9))
    def test_whole_valued_float_renders_as_int(self, whole):
        result = format_channel_number(float(whole))
        self.assertIs(type(result), int)
        self.assertEqual(result, whole)

    @given(value=st.floats(-(10**9), 10**9, allow_nan=False).filter(lambda f: f != int(f)))
    @example(value=12.5)
    def test_fractional_float_is_returned_unchanged(self, value):
        self.assertEqual(format_channel_number(value), value)

    @given(sentinel=st.sampled_from(["", None, "-", 0]))
    def test_none_returns_the_caller_sentinel(self, sentinel):
        self.assertIs(format_channel_number(None, empty=sentinel), sentinel)


class CoerceChannelProfileIdsProperties(SimpleTestCase):
    def setUp(self):
        # custom_properties_as_dict warns on every non-JSON string; not the subject here.
        patcher = mock.patch("core.utils.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(value=json_values)
    def test_any_json_value_returns_a_dict_with_int_ids(self, value):
        result = coerce_channel_profile_ids(value)
        self.assertIsInstance(result, dict)
        if "channel_profile_ids" in result:
            self.assertTrue(all(type(i) is int for i in result["channel_profile_ids"]))

    @given(props=json_dicts, ids=st.lists(json_values, max_size=5))
    @example(props={}, ids=["3", 4, "x", None, 2.0])  # the UI MultiSelect sends strings
    def test_ids_are_the_int_convertible_items_in_order(self, props, ids):
        props = dict(props, channel_profile_ids=ids)
        expected = []
        for item in ids:  # independent oracle: exactly what int() accepts
            try:
                expected.append(int(item))
            except (TypeError, ValueError):
                pass
        result = coerce_channel_profile_ids(props)
        self.assertEqual(result["channel_profile_ids"], expected)
        self.assertEqual(
            {k: v for k, v in result.items() if k != "channel_profile_ids"},
            {k: v for k, v in props.items() if k != "channel_profile_ids"},
        )

    @given(props=json_dicts)
    def test_input_dict_is_not_mutated(self, props):
        props = dict(props, channel_profile_ids=["1", 2, "x"])
        snapshot = json.dumps(props, sort_keys=True)
        coerce_channel_profile_ids(props)
        self.assertEqual(json.dumps(props, sort_keys=True), snapshot)

    @given(props=json_dicts)
    def test_json_encoded_string_row_coerces_like_the_dict(self, props):
        props = dict(props, channel_profile_ids=["7", 8])
        self.assertEqual(
            coerce_channel_profile_ids(json.dumps(props)), coerce_channel_profile_ids(props)
        )


class CustomPropertiesDictProperties(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("core.utils.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(value=json_values)
    def test_always_returns_a_dict(self, value):
        self.assertIsInstance(custom_properties_as_dict(value), dict)
        self.assertIsInstance(ensure_custom_properties_dict(value), dict)

    @given(value=json_dicts)
    def test_dict_passes_through_by_identity(self, value):
        self.assertIs(custom_properties_as_dict(value), value)
        self.assertIs(ensure_custom_properties_dict(value), value)

    @given(value=json_dicts)
    def test_json_encoded_dict_string_decodes_to_that_dict(self, value):
        self.assertEqual(custom_properties_as_dict(json.dumps(value)), value)

    @given(value=json_values.filter(lambda v: not isinstance(v, dict)))
    def test_json_encoded_non_dict_string_is_empty(self, value):
        self.assertEqual(custom_properties_as_dict(json.dumps(value)), {})

    @given(value=st.text(max_size=30))
    @example(value="{not json")
    def test_ensure_agrees_with_as_dict_for_strings(self, value):
        self.assertEqual(ensure_custom_properties_dict(value), custom_properties_as_dict(value))
