"""Property tests for catch-up duration resolution and URL layout helpers.

* ``resolve_catchup_duration`` prefers a usable client hint over EPG, falls
  back to ``DEFAULT_DURATION_MINUTES`` when the hint is unusable and the
  channel carries no EPG data (the DB-free path), and never raises.
* ``client_timeshift_url_layout`` returns ``query`` exactly when the inbound
  path mentions ``timeshift.php`` and ``path`` otherwise — case-insensitive.
* ``format_timestamp_as_*`` reshapers return the input unchanged when the
  timestamp cannot be parsed (callers rely on passthrough for provider
  tolerance), and emit the documented shape when it can.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

import re
from datetime import datetime

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    DEFAULT_DURATION_MINUTES,
    MAX_DURATION_MINUTES,
    client_timeshift_url_layout,
    format_timestamp_as_colon_dash,
    format_timestamp_as_colon_seconds,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
    parse_catchup_timestamp,
    resolve_catchup_duration,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class _NoEpgChannel:
    epg_data = None


class _Request:
    def __init__(self, path):
        self.path = path


class ResolveDurationProperties(SimpleTestCase):
    @given(
        hint=st.one_of(st.none(), st.text(max_size=16), st.integers()),
    )
    def test_hint_precedence_and_fallback(self, hint):
        result = resolve_catchup_duration(_NoEpgChannel(), "2026-05-21:12-55", hint)
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, MAX_DURATION_MINUTES)

    @given(minutes=st.integers(min_value=1, max_value=MAX_DURATION_MINUTES - 5))
    def test_usable_hint_wins_over_epg_fallback(self, minutes):
        result = resolve_catchup_duration(
            _NoEpgChannel(), "2026-05-21:12-55", str(minutes)
        )
        self.assertEqual(result, minutes + 5)

    @given(hint=st.one_of(st.none(), st.integers(max_value=0), st.text(alphabet="abcxyz")))
    def test_unusable_hint_falls_back_to_default_without_epg(self, hint):
        result = resolve_catchup_duration(_NoEpgChannel(), "2026-05-21:12-55", hint)
        self.assertEqual(result, DEFAULT_DURATION_MINUTES)


class UrlLayoutProperties(SimpleTestCase):
    @given(path=st.one_of(st.none(), st.text(max_size=80)))
    def test_query_only_for_timeshift_php(self, path):
        layout = client_timeshift_url_layout(_Request(path))
        self.assertIn(layout, ("query", "path"))
        expected = "query" if path and "timeshift.php" in path.lower() else "path"
        self.assertEqual(layout, expected)

    @given(path=st.text(max_size=60))
    def test_case_insensitive(self, path):
        lower = client_timeshift_url_layout(_Request(path.lower()))
        upper = client_timeshift_url_layout(_Request(path.upper()))
        self.assertEqual(lower, upper)


class ReshapeProperties(SimpleTestCase):
    RESHAPERS = (
        (format_timestamp_as_colon_dash, r"^\d{4}-\d{2}-\d{2}:\d{2}-\d{2}$"),
        (format_timestamp_as_colon_seconds, r"^\d{4}-\d{2}-\d{2}:\d{2}:\d{2}:\d{2}$"),
        (format_timestamp_as_sql_datetime, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"),
        (format_timestamp_as_underscore, r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}$"),
    )

    @given(value=st.one_of(st.text(max_size=48), st.none()))
    def test_never_raises(self, value):
        for reshape, _pattern in self.RESHAPERS:
            reshape(value)

    @given(value=st.text(max_size=48))
    def test_unparseable_passthrough(self, value):
        if parse_catchup_timestamp(value) is not None:
            return
        for reshape, _pattern in self.RESHAPERS:
            self.assertEqual(reshape(value), value)

    @given(
        value=st.datetimes(
            min_value=datetime(1970, 1, 1), max_value=datetime(9999, 12, 31)
        )
    )
    def test_parseable_emits_documented_shape(self, value):
        iso = value.isoformat(timespec="seconds")
        for reshape, pattern in self.RESHAPERS:
            self.assertRegex(reshape(iso), pattern)
