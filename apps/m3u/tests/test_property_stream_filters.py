"""Property-based tests for M3U stream filtering and batch-count parsing.

These encode invariants the implementation actually promises, read from the code:

``_stream_passes_m3u_filters`` (apps/m3u/tasks.py):
  - returns a bool for arbitrary name/url/group text (never raises on text);
  - with no compiled filters every stream passes;
  - a single exclude filter rejects exactly the streams whose *target* field
    matches its pattern, and passes the rest;
  - a single include filter still passes non-matching streams (include filters
    only reject when they themselves match, per the ``return not exclude``
    contract) — so a lone include filter never rejects anything;
  - the target field is selected by ``filter_type`` ("url" -> url,
    "group" -> group_title, anything else -> name);
  - a None target is treated as "" (the ``target or ""`` guard).

``_batch_stream_count_message`` / ``_parse_batch_stream_counts`` round-trip:
  - ``_parse_batch_stream_counts`` is total: arbitrary input returns a 3-tuple
    of ints and never raises;
  - non-string input returns ``(0, 0, 0)``;
  - a message produced by ``_batch_stream_count_message`` parses back to exactly
    the counts it was built from.

All tests are ``SimpleTestCase``-based (no DB, no Redis) and use a derandomized
CI profile so runs stay fast and reproducible.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _batch_stream_count_message,
    _compile_m3u_stream_filters,
    _parse_batch_stream_counts,
    _stream_passes_m3u_filters,
)

# CI-deterministic profile (registered/loaded at import; the Django test runner
# has no pytest-style conftest hook). derandomize keeps runs reproducible;
# deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Text that is safe to embed in a regex search target and in log lines.
_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters=("\x00",)
    ),
    max_size=60,
)

# A small alphabet of regex-safe patterns so generated filters compile and match
# often enough to exercise both branches. Includes a wildcard-bearing variant.
_PATTERN = st.sampled_from(
    ["news", "sport", "adult", "hd", "News", "HD", r"\d+", "channel", "x"]
)


def _make_filter(filter_type, exclude, pattern, case_sensitive=True):
    obj = MagicMock()
    obj.filter_type = filter_type
    obj.exclude = exclude
    obj.regex_pattern = pattern
    obj.custom_properties = {"case_sensitive": case_sensitive}
    return obj


def _target_for(filter_type, name, url, group_title):
    if filter_type == "url":
        return url
    if filter_type == "group":
        return group_title
    return name


class StreamPassesM3UFiltersPropertyTests(SimpleTestCase):
    @given(name=_TEXT, url=_TEXT, group=_TEXT)
    def test_no_filters_everything_passes(self, name, url, group):
        self.assertTrue(_stream_passes_m3u_filters(name, url, group, []))

    @given(name=_TEXT, url=_TEXT, group=_TEXT)
    def test_returns_bool_and_never_raises_on_text(self, name, url, group):
        compiled = _compile_m3u_stream_filters([_make_filter("name", True, "news")])
        result = _stream_passes_m3u_filters(name, url, group, compiled)
        self.assertIsInstance(result, bool)

    @given(
        name=_TEXT,
        url=_TEXT,
        group=_TEXT,
        pattern=_PATTERN,
        filter_type=st.sampled_from(["group", "name", "url"]),
        case_sensitive=st.booleans(),
    )
    def test_exclude_filter_rejects_exactly_matching_target(
        self, name, url, group, pattern, filter_type, case_sensitive
    ):
        """An exclude filter rejects iff its target field matches the pattern."""
        compiled = _compile_m3u_stream_filters(
            [_make_filter(filter_type, True, pattern, case_sensitive)]
        )
        result = _stream_passes_m3u_filters(name, url, group, compiled)

        target = _target_for(filter_type, name, url, group) or ""
        import re as _re

        flags = 0 if case_sensitive else _re.IGNORECASE
        matched = _re.compile(pattern, flags).search(target) is not None
        self.assertEqual(result, not matched)

    @given(
        name=_TEXT,
        url=_TEXT,
        group=_TEXT,
        pattern=_PATTERN,
        filter_type=st.sampled_from(["group", "name", "url"]),
    )
    def test_lone_include_filter_never_rejects(
        self, name, url, group, pattern, filter_type
    ):
        """A single include filter passes everything: it only rejects when it
        matches (``return not exclude``), and non-matching streams fall through
        to the default ``True``."""
        compiled = _compile_m3u_stream_filters(
            [_make_filter(filter_type, False, pattern)]
        )
        self.assertTrue(_stream_passes_m3u_filters(name, url, group, compiled))

    @given(url=_TEXT, pattern=_PATTERN)
    def test_none_target_treated_as_empty_string(self, url, pattern):
        """name=None hits the ``target or ""`` guard rather than raising."""
        compiled = _compile_m3u_stream_filters([_make_filter("name", True, pattern)])
        result = _stream_passes_m3u_filters(None, url, "grp", compiled)
        import re as _re

        matched = _re.compile(pattern).search("") is not None
        self.assertEqual(result, not matched)


class BatchStreamCountsPropertyTests(SimpleTestCase):
    @given(
        created=st.integers(min_value=0, max_value=10**7),
        updated=st.integers(min_value=0, max_value=10**7),
        unchanged=st.integers(min_value=0, max_value=10**7),
    )
    def test_message_round_trips_through_parser(self, created, updated, unchanged):
        """A message built by _batch_stream_count_message parses back exactly."""
        msg = _batch_stream_count_message(created, updated, unchanged)
        self.assertEqual(
            _parse_batch_stream_counts(msg), (created, updated, unchanged)
        )

    @given(result=st.one_of(st.none(), st.integers(), st.lists(st.integers())))
    def test_non_string_returns_zeros(self, result):
        self.assertEqual(_parse_batch_stream_counts(result), (0, 0, 0))

    @given(result=st.text(max_size=120))
    def test_arbitrary_string_is_total_and_never_raises(self, result):
        parsed = _parse_batch_stream_counts(result)
        self.assertIsInstance(parsed, tuple)
        self.assertEqual(len(parsed), 3)
        for v in parsed:
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)
