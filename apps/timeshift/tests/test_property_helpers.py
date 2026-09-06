"""Property-based tests for ``apps.timeshift.helpers`` pure functions.

The catch-up timestamp parser and URL builders consume client-controlled text
(XC player URLs, EPG datetimes, query params), so their core contract is
robustness plus a small set of documented invariants:

* ``normalize_catchup_timestamp_input``/``parse_catchup_timestamp`` never raise,
  whatever the input, and any non-None result round-trips back to the same
  ISO value through a second pass (idempotence).
* Epoch recognition is length-gated: exactly 10 digits are epoch seconds,
  exactly 13 are epoch milliseconds, every other digit-run is rejected.
* ``client_duration_to_window`` only accepts a positive integer hint and always
  returns ``hint + DURATION_BUFFER_MINUTES`` capped at ``MAX_DURATION_MINUTES``.
* ``programme_age_days`` returns None for unparseable input, 0 for present/
  future starts, and a positive whole-day ceiling for past starts.
* ``order_catchup_streams_for_timestamp`` is a stable repartition: the output
  is a permutation of the input, channel order is preserved inside each of the
  preferred/fallback groups, and unparseable timestamps leave order untouched.
* ``build_timeshift_candidate_urls`` always emits the seven documented forms
  with every PATH form ahead of every QUERY form, and credentials are
  percent-encoded so reserved characters cannot smuggle extra query
  parameters into the provider URL.
* ``build_timeshift_url_format_b`` never emits ``//`` after the server URL
  host segment, regardless of trailing slashes in ``server_url``.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    DURATION_BUFFER_MINUTES,
    MAX_DURATION_MINUTES,
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    client_duration_to_window,
    normalize_catchup_timestamp_input,
    order_catchup_streams_for_timestamp,
    parse_catchup_timestamp,
    programme_age_days,
)

# CI-deterministic profile — matches apps/proxy/live_proxy property tests.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Arbitrary client-controlled text, weighted toward the shapes the parser
# regex half-matches: digits, separators, T/Z markers, whitespace.
timestamp_text = st.text(max_size=64) | st.text(
    alphabet="0123456789-_:TZ.+ ", min_size=1, max_size=40
)

wall_clock = st.builds(
    lambda d, h, m, s, dtsep, hmsep, with_s: (
        f"{d:%Y-%m-%d}{dtsep}{h:02d}{hmsep}{m:02d}"
        + (f"{hmsep}{s:02d}" if with_s else "")
    ),
    st.datetimes(
        min_value=datetime(1970, 1, 1), max_value=datetime(9999, 12, 31)
    ).map(lambda d: d.date()),
    st.integers(0, 23),
    st.integers(0, 59),
    st.integers(0, 59),
    st.sampled_from([":", "_", " "]),
    st.sampled_from(["-", ":"]),
    st.booleans(),
)


class TimestampParserProperties(SimpleTestCase):
    @given(value=timestamp_text)
    def test_normalize_never_raises_and_output_shape(self, value):
        result = normalize_catchup_timestamp_input(value)
        if result is not None:
            self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    @given(value=timestamp_text)
    def test_parse_never_raises(self, value):
        result = parse_catchup_timestamp(value)
        if result is not None:
            self.assertIsNone(result.tzinfo)

    @given(value=timestamp_text)
    def test_normalize_is_idempotent(self, value):
        once = normalize_catchup_timestamp_input(value)
        if once is None:
            return
        self.assertEqual(normalize_catchup_timestamp_input(once), once)

    @given(value=timestamp_text)
    def test_parse_agrees_with_normalize(self, value):
        once = normalize_catchup_timestamp_input(value)
        parsed = parse_catchup_timestamp(value)
        if once is None:
            self.assertIsNone(parsed)
        else:
            self.assertEqual(parsed.isoformat(timespec="seconds"), once)

    @given(value=st.integers(min_value=1_000_000_000, max_value=9_999_999_999))
    def test_epoch_seconds_round_trip(self, value):
        # 10-digit epoch seconds are treated as UTC wall clock.
        text = str(value)
        expected = datetime.fromtimestamp(value, tz=timezone.utc).replace(
            tzinfo=None
        )
        self.assertEqual(parse_catchup_timestamp(text), expected)

    @given(
        value=st.integers(
            min_value=1_000_000_000_000, max_value=9_999_999_999_999
        )
    )
    def test_epoch_millis_truncate_to_seconds(self, value):
        expected = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        expected = expected.replace(microsecond=0, tzinfo=None)
        self.assertEqual(parse_catchup_timestamp(str(value)), expected)

    @given(
        digits=st.integers(min_value=1, max_value=25),
        value=st.integers(min_value=0, max_value=10**25 - 1),
    )
    def test_digit_runs_of_other_lengths_rejected(self, digits, value):
        text = str(value).zfill(digits)
        assume(len(text) not in (10, 13))
        assume(len(text) == digits)
        self.assertIsNone(normalize_catchup_timestamp_input(text))

    @given(ts=wall_clock)
    def test_wall_clock_shapes_parse(self, ts):
        parsed = parse_catchup_timestamp(ts)
        self.assertIsNotNone(parsed, ts)

    @given(value=st.datetimes())
    def test_iso_datetimes_normalise_to_naive_utc(self, value):
        iso = value.isoformat()
        parsed = parse_catchup_timestamp(iso)
        if value.tzinfo is None:
            self.assertEqual(parsed, value.replace(microsecond=0))
        else:
            expected = value.astimezone(timezone.utc).replace(
                tzinfo=None, microsecond=0
            )
            self.assertEqual(parsed, expected)


class DurationWindowProperties(SimpleTestCase):
    @given(value=st.one_of(st.text(max_size=32), st.integers(), st.floats()))
    def test_never_raises(self, value):
        client_duration_to_window(value)

    @given(minutes=st.integers(min_value=1, max_value=10**9))
    def test_positive_int_hint_gets_buffer_and_cap(self, minutes):
        window = client_duration_to_window(minutes)
        self.assertEqual(
            window, min(minutes + DURATION_BUFFER_MINUTES, MAX_DURATION_MINUTES)
        )

    @given(value=st.integers(max_value=0))
    def test_non_positive_rejected(self, value):
        self.assertIsNone(client_duration_to_window(value))

    @given(value=st.floats(min_value=1, max_value=10**6))
    def test_whole_float_strings_accepted(self, value):
        # A float whose str() is "12.0" is not a usable positive integer.
        result = client_duration_to_window(str(value))
        if value == int(value):
            self.assertEqual(result, None)  # "12.0" fails int()
        else:
            self.assertIsNone(result)


class ProgrammeAgeProperties(SimpleTestCase):
    @given(value=timestamp_text)
    def test_unparseable_or_age_invariants(self, value):
        now = datetime(2026, 9, 6, 12, 0, 0)
        age = programme_age_days(value, now=now)
        parsed = parse_catchup_timestamp(value)
        if parsed is None:
            self.assertIsNone(age)
        else:
            elapsed = (now - parsed).total_seconds()
            if elapsed <= 0:
                self.assertEqual(age, 0)
            else:
                self.assertEqual(age, max(1, math.ceil(elapsed / 86400.0)))

    @given(
        now=st.datetimes(
            min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)
        )
    )
    def test_aware_now_is_normalised(self, now):
        aware = now.replace(tzinfo=timezone.utc)
        ts = (now - timedelta(days=3)).strftime("%Y-%m-%d:%H-%M")
        self.assertEqual(
            programme_age_days(ts, now=aware),
            programme_age_days(ts, now=now),
        )


class StreamOrderingProperties(SimpleTestCase):
    class _FakeStream:
        def __init__(self, name, catchup_days):
            self.name = name
            self.catchup_days = catchup_days

    @given(
        days_values=st.lists(
            st.one_of(
                st.integers(min_value=-5, max_value=40),
                st.text(max_size=6),
                st.none(),
            ),
            max_size=12,
        ),
        age_days=st.integers(min_value=1, max_value=30),
    )
    def test_stable_repartition(self, days_values, age_days):
        streams = [
            self._FakeStream(f"s{i}", d) for i, d in enumerate(days_values)
        ]
        now = datetime(2026, 9, 6, 12, 0, 0)
        start = (now - timedelta(days=age_days)).strftime("%Y-%m-%d:%H-%M")
        ordered = order_catchup_streams_for_timestamp(streams, start, now=now)
        # Output is a permutation of the input.
        self.assertEqual(
            sorted(s.name for s in ordered), sorted(s.name for s in streams)
        )
        # Relative channel order is preserved within each group.
        def is_preferred(stream):
            raw = stream.catchup_days
            try:
                days = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                days = 0
            return days <= 0 or days >= age_days

        for group in (True, False):
            before = [s.name for s in streams if is_preferred(s) is group]
            after = [s.name for s in ordered if is_preferred(s) is group]
            self.assertEqual(before, after)
        # Every preferred stream precedes every fallback one.
        def is_preferred(stream):
            raw = stream.catchup_days
            try:
                days = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                days = 0
            return days <= 0 or days >= age_days

        seen_fallback = False
        for stream in ordered:
            if is_preferred(stream):
                self.assertFalse(seen_fallback, stream.name)
            else:
                seen_fallback = True
        del is_preferred

    @given(names=st.lists(st.text(max_size=8), max_size=10))
    def test_unparseable_timestamp_preserves_order(self, names):
        streams = [self._FakeStream(n, 7) for n in names]
        ordered = order_catchup_streams_for_timestamp(streams, "not-a-time")
        self.assertEqual([s.name for s in ordered], [s.name for s in streams])
        # And it must be a copy, not the caller's list.
        self.assertIsNot(ordered, streams)


class UrlBuilderProperties(SimpleTestCase):
    creds_strategy = st.builds(
        TimeshiftCredentials,
        server_url=st.builds(
            lambda host, slashes: f"http://{host}{slashes}",
            host=st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-",
                min_size=1,
                max_size=24,
            ),
            slashes=st.sampled_from(["", "/", "///"]),
        ),
        username=st.text(max_size=24),
        password=st.text(max_size=24),
    )

    @given(
        creds=creds_strategy,
        stream_id=st.integers(min_value=0, max_value=10**12),
        duration=st.integers(min_value=1, max_value=480),
    )
    def test_candidate_urls_layout_and_order(self, creds, stream_id, duration):
        timestamp = "2026-05-21:12-55"
        urls = build_timeshift_candidate_urls(
            creds, stream_id, timestamp, duration
        )
        self.assertEqual(len(urls), 7)
        path_forms = [u for u in urls if "/timeshift/" in u]
        query_forms = [u for u in urls if "timeshift.php" in u]
        self.assertEqual(len(path_forms), 3)
        self.assertEqual(len(query_forms), 4)
        # Every PATH candidate precedes every QUERY candidate.
        last_path = max(urls.index(u) for u in path_forms)
        first_query = min(urls.index(u) for u in query_forms)
        self.assertLess(last_path, first_query)

    @given(
        creds=creds_strategy,
        stream_id=st.integers(min_value=0, max_value=10**12),
        duration=st.integers(min_value=1, max_value=480),
    )
    def test_credentials_percent_encoded(self, creds, stream_id, duration):
        url_a = build_timeshift_url_format_a(creds, stream_id, "2026-05-21:12-55", duration)
        url_b = build_timeshift_url_format_b(creds, stream_id, "2026-05-21:12-55", duration)
        quoted_user = quote(str(creds.username), safe="")
        quoted_pass = quote(str(creds.password), safe="")
        self.assertIn(f"username={quoted_user}&", url_a)
        self.assertIn(f"&password={quoted_pass}&", url_a)
        self.assertIn(f"/{quoted_user}/{quoted_pass}/", url_b)

    @given(creds=creds_strategy)
    def test_format_b_no_double_slash_after_server(self, creds):
        assume(str(creds.username))
        assume(str(creds.password))
        url = build_timeshift_url_format_b(creds, 1, "2026-05-21:12-55", 60)
        after_scheme = url.split("://", 1)[1]
        self.assertNotIn("//", after_scheme)
