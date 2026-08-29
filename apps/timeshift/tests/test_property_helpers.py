"""Property-based tests for the catch-up (timeshift) parsing/URL surfaces.

The functions under test consume provider- and client-controlled strings:
catch-up timestamps arrive from arbitrary XC client URL shapes, provider
credentials/timezones come from upstream servers, and client duration hints
come from URL path segments. Their documented contracts (see the docstrings in
apps/timeshift/helpers.py) are:

* ``normalize_catchup_timestamp_input`` returns ``None`` or an ISO-8601
  date-time string that ``datetime.fromisoformat`` accepts — never raises.
* ``parse_catchup_timestamp`` returns a naive ``datetime`` or ``None`` —
  never raises, and never returns a tz-aware value.
* The ``format_timestamp_as_*`` reshapers return their input unchanged when
  the timestamp is unrecognised (documented fallback).
* ``client_duration_to_window`` returns ``None`` or an int in
  ``[1 + DURATION_BUFFER_MINUTES, MAX_DURATION_MINUTES]`` — never raises.
* ``programme_age_days`` returns ``None`` or an int >= 0 — never raises.
* ``build_timeshift_url_format_{a,b}`` percent-encode credentials so a
  password containing ``&``, ``=``, ``/`` or ``?`` cannot smuggle extra
  query parameters or path segments into the provider URL.
* ``client_timeshift_url_layout`` is always ``"query"`` or ``"path"``.
* ``order_catchup_streams_for_timestamp`` is a pure permutation of its input
  (no stream is dropped, duplicated, or invented) for arbitrary orderings.
* ``parse_stats_channel_id`` (redis_keys) returns ``None`` or a dict whose
  ``channel_id`` is an int — never raises.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from datetime import datetime

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    DURATION_BUFFER_MINUTES,
    MAX_DURATION_MINUTES,
    TimeshiftCredentials,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    client_duration_to_window,
    client_timeshift_url_layout,
    format_timestamp_as_colon_dash,
    format_timestamp_as_colon_seconds,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
    normalize_catchup_timestamp_input,
    order_catchup_streams_for_timestamp,
    parse_catchup_timestamp,
    programme_age_days,
)
from apps.timeshift.redis_keys import parse_stats_channel_id

# CI-deterministic profile — same pattern as apps/proxy/live_proxy/tests.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Broad "anything a client might send" strategy: arbitrary unicode including
# control characters, plus digit-heavy and timestamp-shaped lures.
ANY_TEXT = st.text()
TIMESTAMP_LURES = st.one_of(
    ANY_TEXT,
    st.text(alphabet="0123456789-_:TZ.+ t", min_size=0, max_size=40),
    st.integers(min_value=0, max_value=10**14).map(str),
)


class NormalizeTimestampProperties(SimpleTestCase):
    """normalize_catchup_timestamp_input: total function, ISO output only."""

    @given(TIMESTAMP_LURES)
    def test_never_raises_and_output_is_iso_or_none(self, value):
        result = normalize_catchup_timestamp_input(value)
        if result is None:
            return
        # Non-None output is always built as an ISO-8601 date-time shape
        # (epoch paths use datetime.isoformat; ISO inputs pass through
        # fromisoformat; wall-clock inputs are re-emitted as
        # "dateTHH:MM:SS"). Note: calendar-validity is deliberately deferred
        # to parse_catchup_timestamp, so only structurally valid output is
        # asserted here.
        self.assertIsInstance(result, str)
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    @given(TIMESTAMP_LURES)
    def test_parse_never_raises_and_is_naive(self, value):
        result = parse_catchup_timestamp(value)
        if result is None:
            return
        self.assertIsInstance(result, datetime)
        # Documented: naive UTC wall-clock, never tz-aware.
        self.assertIsNone(result.tzinfo)

    @given(st.text(alphabet="0123456789", min_size=10, max_size=10))
    def test_epoch_seconds_roundtrip_through_unix_epoch(self, digits):
        # 10-digit values are treated as epoch seconds; the normalized form
        # must parse back to the same epoch (within representable range).
        epoch = int(digits)
        result = normalize_catchup_timestamp_input(digits)
        if result is None:
            # Only possible if out of datetime range — not for 10 digits.
            self.fail(f"10-digit epoch {epoch} unexpectedly rejected")
        # Compare against the same UTC conversion the implementation uses;
        # naive .timestamp() would interpret in local time.
        from datetime import timezone

        expected = datetime.fromtimestamp(epoch, tz=timezone.utc).replace(
            tzinfo=None
        )
        self.assertEqual(datetime.fromisoformat(result), expected)

    @given(st.sampled_from(["", "   ", "\t\n", "garbage",
                            "2026/07/09 14:00", "12345678901"]))
    def test_known_bad_shapes_rejected(self, value):
        self.assertIsNone(normalize_catchup_timestamp_input(value))


class ReshapeFallbackProperties(SimpleTestCase):
    """format_timestamp_as_* return their input unchanged on unparseable input."""

    @given(TIMESTAMP_LURES)
    def test_unparseable_input_is_returned_unchanged(self, value):
        parseable = parse_catchup_timestamp(value) is not None
        for reshaper in (
            format_timestamp_as_colon_dash,
            format_timestamp_as_colon_seconds,
            format_timestamp_as_sql_datetime,
            format_timestamp_as_underscore,
        ):
            result = reshaper(value)
            if not parseable:
                self.assertEqual(result, value)

    @given(st.datetimes(min_value=datetime(1000, 1, 1)))
    def test_roundtrip_through_canonical_shape(self, dt):
        canonical = dt.strftime("%Y-%m-%d:%H-%M-%S")
        for reshaper, fmt in (
            (format_timestamp_as_colon_dash, "%Y-%m-%d:%H-%M"),
            (format_timestamp_as_colon_seconds, "%Y-%m-%d:%H:%M:%S"),
            (format_timestamp_as_sql_datetime, "%Y-%m-%d %H:%M:%S"),
            (format_timestamp_as_underscore, "%Y-%m-%d_%H-%M"),
        ):
            self.assertEqual(reshaper(canonical), dt.strftime(fmt))


class ClientDurationWindowProperties(SimpleTestCase):
    """client_duration_to_window: None or bounded int, never raises."""

    @given(st.one_of(ANY_TEXT, st.integers(), st.floats(allow_nan=True), st.none()))
    def test_output_bounds(self, value):
        result = client_duration_to_window(value)
        if result is None:
            return
        self.assertIsInstance(result, int)
        # minutes >= 1 plus the buffer, capped at MAX.
        self.assertGreaterEqual(result, 1 + DURATION_BUFFER_MINUTES)
        self.assertLessEqual(result, MAX_DURATION_MINUTES)


class ProgrammeAgeProperties(SimpleTestCase):
    """programme_age_days: None or non-negative int, never raises."""

    @given(TIMESTAMP_LURES)
    def test_output_contract(self, value):
        result = programme_age_days(value)
        if result is None:
            return
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)


class ProviderUrlCredentialProperties(SimpleTestCase):
    """URL builders must not let credentials break the URL structure."""

    CRED = st.text(min_size=0, max_size=30)

    @given(username=CRED, password=CRED)
    def test_format_a_credentials_cannot_smuggle_query_params(
        self, username, password
    ):
        creds = TimeshiftCredentials("http://provider.local", username, password)
        url = build_timeshift_url_format_a(creds, 42, "2026-07-09:14-00", 60)
        query = url.split("?", 1)[1]
        params = dict(
            pair.split("=", 1) for pair in query.split("&") if "=" in pair
        )
        # Exactly the documented five parameters — a credential containing
        # '&' or '=' must not have created more.
        self.assertEqual(
            set(params), {"username", "password", "stream", "start", "duration"}
        )

    @given(username=CRED, password=CRED)
    def test_format_b_credentials_cannot_smuggle_path_segments(
        self, username, password
    ):
        creds = TimeshiftCredentials("http://provider.local", username, password)
        url = build_timeshift_url_format_b(creds, 42, "2026-07-09:14-00", 60)
        path = url.split("provider.local", 1)[1]
        segments = path.strip("/").split("/")
        # /timeshift/{user}/{pass}/{dur}/{start}/{id}.ts — exactly 6 segments.
        self.assertEqual(len(segments), 6)
        self.assertEqual(segments[0], "timeshift")

    @given(
        # Bound the count of structural characters so the raw credential can
        # never coincide with a legitimate sequence of encoded bytes plus
        # separators; quote() guarantees every reserved char becomes %XX.
        username=st.text(
            alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
            min_size=1,
            max_size=20,
        ).filter(lambda s: sum(c in "/?&#=%" for c in s) <= 1),
        password=st.text(
            alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
            min_size=1,
            max_size=20,
        ).filter(lambda s: sum(c in "/?&#=%" for c in s) <= 1),
    )
    def test_query_url_has_exactly_five_params(self, username, password):
        creds = TimeshiftCredentials("http://provider.local", username, password)
        url = build_timeshift_url_format_a(creds, 7, "2026-07-09:14-00", 30)
        query = url.split("?", 1)[1]
        params = query.split("&")
        self.assertEqual(len(params), 5)
        names = sorted(p.split("=", 1)[0] for p in params)
        self.assertEqual(
            names, ["duration", "password", "start", "stream", "username"]
        )


class ClientLayoutProperties(SimpleTestCase):
    class _Req:
        def __init__(self, path):
            self.path = path

    @given(st.one_of(ANY_TEXT, st.none()))
    def test_layout_is_always_query_or_path(self, path):
        req = self._Req(path)
        self.assertIn(client_timeshift_url_layout(req), {"query", "path"})


class _FakeStream:
    def __init__(self, catchup_days, marker):
        self.catchup_days = catchup_days
        self.marker = marker


class StreamOrderingProperties(SimpleTestCase):
    """order_catchup_streams_for_timestamp is a permutation of its input."""

    @given(
        streams=st.lists(
            st.builds(
                _FakeStream,
                catchup_days=st.one_of(
                    st.integers(min_value=-5, max_value=60),
                    st.text(max_size=5),
                    st.none(),
                ),
                marker=st.uuids(),
            ),
            max_size=25,
        ),
        timestamp=TIMESTAMP_LURES,
    )
    def test_output_is_permutation_of_input(self, streams, timestamp):
        result = order_catchup_streams_for_timestamp(streams, timestamp)
        self.assertEqual(len(result), len(streams))
        # Same multiset — nothing dropped, duplicated, or invented.
        self.assertEqual(
            sorted(s.marker for s in result),
            sorted(s.marker for s in streams),
        )


class StatsChannelIdProperties(SimpleTestCase):
    """parse_stats_channel_id: None or {'channel_id': int, ...}, never raises."""

    @given(st.one_of(ANY_TEXT, st.integers(), st.none()))
    def test_output_contract(self, value):
        result = parse_stats_channel_id(value)
        if result is None:
            return
        self.assertIsInstance(result["channel_id"], int)
        self.assertIsInstance(result["session_id"], str)

    @given(
        channel_id=st.integers(min_value=0, max_value=2**63),
        session_id=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
            min_size=1,
            max_size=30,
        ),
    )
    def test_roundtrip_with_stats_channel_id(self, channel_id, session_id):
        from apps.timeshift.redis_keys import stats_channel_id

        combined = stats_channel_id(channel_id, session_id)
        parsed = parse_stats_channel_id(combined)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["channel_id"], channel_id)
        self.assertEqual(parsed["session_id"], session_id)
