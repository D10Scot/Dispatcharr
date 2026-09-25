"""Property-based tests for ``parse_xmltv_time`` (apps/epg/tasks.py:2504).

Every ``<programme start= stop=>`` of every provider file goes through this
parser. Its contract, read from the seed code:

* ``YYYYMMDDHHMMSS`` alone is a UTC wall clock (``make_aware(..., utc)``).
* ``YYYYMMDDHHMMSS ±HHMM`` is local time at that offset, returned in UTC.
* Anything else raises ``ValueError`` and nothing else: the ``except`` block
  logs and re-raises, and both bulk parsers (``:1730``, ``:2222``) catch per
  programme. C-2 (#76, #156) makes the two byte-offset helpers catch it too
  and deliberately keeps this raising contract, so it is pinned here.
* C-2 (#75): the adjacent form ``YYYYMMDDHHMMSS±HHMM`` is the same instant as
  the spaced form. At seed the adjacent offset is silently read as UTC.

Closes the parse_xmltv_time part of #202 (and duplicates #274, #158, #74).
"""

import logging
import string
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.epg import tasks as epg_tasks
from apps.epg.tasks import parse_xmltv_time

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# Wall-clock fields. Day <= 28 keeps every month valid; the base range keeps
# a +/-23:59 shift inside datetime's year range.
wall_clocks = st.builds(
    datetime,
    year=st.integers(1971, 2100),
    month=st.integers(1, 12),
    day=st.integers(1, 28),
    hour=st.integers(0, 23),
    minute=st.integers(0, 59),
    second=st.integers(0, 59),
)
# dt_timezone accepts |offset| < 24h, so every HH in 00..23 and MM in 00..59
# is a valid offset. HH=24 is the #76 counterexample and must raise.
offsets = st.tuples(
    st.sampled_from("+-"), st.integers(0, 23), st.integers(0, 59)
)

# Corrupt-provider text, biased towards the timestamp alphabet so that most
# draws get past the 14-character strptime and into the offset branch.
junk = st.one_of(
    st.text(max_size=40),
    st.text(alphabet=string.digits + "+- :ZT.", max_size=30),
    st.builds(
        lambda base, tail: base + tail,
        st.text(alphabet=string.digits, min_size=14, max_size=14),
        st.text(alphabet=string.digits + "+- ", max_size=8),
    ),
)


def _stamp(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def _expected_utc(dt, sign, hh, mm):
    """Oracle: local wall clock at +/-HH:MM, as a UTC instant, by arithmetic."""
    delta = timedelta(hours=hh, minutes=mm)
    naive_utc = dt - delta if sign == "+" else dt + delta
    return naive_utc.replace(tzinfo=dt_timezone.utc)


class _QuietParserLog(SimpleTestCase):
    """parse_xmltv_time logs every failure at ERROR with a traceback; silence
    it for the test so 200 malformed draws do not flood the CI log."""

    def setUp(self):
        for level in ("error", "warning"):
            patcher = mock.patch.object(epg_tasks.logger, level)
            patcher.start()
            self.addCleanup(patcher.stop)


class ParseXmltvTimeProperties(_QuietParserLog):
    @given(dt=wall_clocks)
    def test_a_bare_timestamp_is_the_same_wall_clock_in_utc(self, dt):
        result = parse_xmltv_time(_stamp(dt))
        self.assertEqual(result, dt.replace(tzinfo=dt_timezone.utc))
        self.assertEqual(result.utcoffset(), timedelta(0))

    @given(dt=wall_clocks, offset=offsets)
    def test_a_spaced_offset_is_local_time_at_that_offset_returned_in_utc(
        self, dt, offset
    ):
        sign, hh, mm = offset
        result = parse_xmltv_time(f"{_stamp(dt)} {sign}{hh:02d}{mm:02d}")
        self.assertEqual(result, _expected_utc(dt, sign, hh, mm))
        self.assertEqual(result.utcoffset(), timedelta(0))

    @example(dt=datetime(2026, 7, 28, 18, 30, 0), offset=("+", 5, 30))  # #75
    @example(dt=datetime(2026, 7, 28, 18, 30, 0), offset=("-", 8, 0))  # #75
    @given(dt=wall_clocks, offset=offsets)
    def test_an_adjacent_offset_is_the_same_instant_as_the_spaced_form(
        self, dt, offset
    ):
        sign, hh, mm = offset
        spaced = parse_xmltv_time(f"{_stamp(dt)} {sign}{hh:02d}{mm:02d}")
        adjacent = parse_xmltv_time(f"{_stamp(dt)}{sign}{hh:02d}{mm:02d}")
        self.assertEqual(adjacent, spaced)

    @example(junk="20260728183000 +2400")  # #76: out-of-range offset hour
    @example(junk="20260728183000 +2460")  # #156: out-of-range offset minute
    @example(junk="20260728183000+2400")  # #75 x #76: adjacent and out of range
    @given(junk=junk)
    def test_arbitrary_text_raises_only_value_error_or_parses_to_aware_utc(
        self, junk
    ):
        try:
            result = parse_xmltv_time(junk)
        except ValueError:
            return  # the documented contract every caller catches
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.utcoffset(), timedelta(0))

    def test_out_of_range_offsets_keep_raising_value_error(self):
        # C-2 fixes #76 in the callers, not here: the raise is the contract.
        for stamp in ("20260728183000 +2400", "20260728183000 +2460"):
            with self.subTest(stamp=stamp):
                with self.assertRaises(ValueError):
                    parse_xmltv_time(stamp)
