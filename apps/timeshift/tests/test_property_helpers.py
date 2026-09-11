"""Property-based tests for the timeshift/catch-up pure parsing surfaces.

The catch-up path consumes client-controlled text on every tune: the XC
timestamp in the URL, the ``Range`` header, and the upstream provider's
``Content-Range``/``Content-Length`` headers. The core contract these
properties pin is the one the code already documents:

* the parsers never raise, whatever the bytes contain — every malformed value
  degrades to ``None`` / "unchanged input" so a hostile or buggy IPTV client
  cannot 500 the relay;
* ``parse_catchup_timestamp`` round-trips through ``normalize_*`` for every
  shape the docstring advertises, and naive calendar validity is enforced;
* the duration window helpers honour their documented bounds
  (``0 < window <= MAX_DURATION_MINUTES``);
* the stats position math stays inside ``[0, duration_secs]``;
* downstream length headers are well-formed RFC 7233 for any representable
  upstream combination.

Runs without Redis or the database (SimpleTestCase, pure functions). The
Redis-backed session/pool surfaces in ``sessions.py``/``stats.py`` are covered
by ``test_sessions.py``/``test_stats.py`` and are deliberately out of scope.
"""

import math
import re
from datetime import datetime, timedelta, timezone

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
    convert_timestamp_to_provider_tz,
    normalize_catchup_timestamp_input,
    order_catchup_streams_for_timestamp,
    parse_catchup_timestamp,
    programme_age_days,
)
from apps.timeshift.redis_keys import parse_stats_channel_id
from apps.timeshift.stats import (
    EOF_PROBE_TAIL_BYTES,
    _client_paused,
    compute_playback_base_from_byte_range,
    compute_playback_position_secs,
    resolve_stats_playback_fields,
)
from apps.timeshift.views import (
    _build_downstream_length_headers,
    _cap_open_ended_range,
    _is_full_restart_range,
    _is_near_eof_probe,
    _map_client_range_through_presentation,
    _parse_client_range,
    _parse_content_range_header,
    _parse_range_start,
    _pool_int_field,
    _presentation_relative_content_range,
)

# CI-deterministic profile — see live_proxy test_property_ts_realignment.py.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Text biased toward the shapes these parsers key on.
_garbage = st.text(max_size=120) | st.text(
    alphabet="0123456789-_:T Z.+bts/=*\x00\r\n", max_size=120
)

_valid_date_times = st.datetimes(
    min_value=datetime(1970, 1, 1), max_value=datetime(9999, 12, 31)
)

# 10-digit epoch seconds: the only all-digit shape normalize accepts for seconds
# (length-checked before conversion). 10 digits spans 2001-2286.
_epoch_seconds = st.integers(min_value=1_000_000_000, max_value=9_999_999_999)
# 13-digit epoch milliseconds: the only all-digit shape accepted for millis.
_epoch_millis = st.integers(min_value=1_000_000_000_000, max_value=9_999_999_999_999)

_non_negative_ints = st.integers(min_value=0, max_value=10**15)


def _creds():
    return TimeshiftCredentials("http://example.test", "user@name", "p@ss/w:rd")


def _is_utf8(data):
    try:
        data.decode()
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# normalize/parse catch-up timestamp
# ---------------------------------------------------------------------------


class TimestampParsingProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), _garbage, st.integers(), st.floats(allow_nan=False, allow_infinity=False)))
    def test_normalize_never_raises(self, value):
        # May return a string or None, but must not raise.
        normalize_catchup_timestamp_input(value)

    @given(value=st.one_of(st.none(), _garbage))
    def test_parse_never_raises_and_returns_datetime_or_none(self, value):
        result = parse_catchup_timestamp(value)
        self.assertTrue(result is None or isinstance(result, datetime))

    @given(dt=_valid_date_times)
    def test_roundtrip_colon_dash(self, dt):
        rendered = dt.strftime("%Y-%m-%d:%H-%M")
        parsed = parse_catchup_timestamp(rendered)
        self.assertEqual(parsed, dt.replace(second=0, microsecond=0))

    @given(dt=_valid_date_times)
    def test_roundtrip_underscore(self, dt):
        rendered = dt.strftime("%Y-%m-%d_%H-%M")
        parsed = parse_catchup_timestamp(rendered)
        self.assertEqual(parsed, dt.replace(second=0, microsecond=0))

    @given(dt=_valid_date_times)
    def test_roundtrip_sql(self, dt):
        rendered = dt.strftime("%Y-%m-%d %H:%M:%S")
        parsed = parse_catchup_timestamp(rendered)
        self.assertEqual(parsed, dt.replace(microsecond=0))

    @given(dt=_valid_date_times)
    def test_roundtrip_colon_seconds(self, dt):
        rendered = dt.strftime("%Y-%m-%d:%H:%M:%S")
        parsed = parse_catchup_timestamp(rendered)
        self.assertEqual(parsed, dt.replace(microsecond=0))

    @given(epoch=_epoch_seconds)
    def test_epoch_seconds_roundtrip(self, epoch):
        rendered = str(epoch)
        parsed = parse_catchup_timestamp(rendered)
        self.assertIsNotNone(parsed)
        expected = datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
        self.assertEqual(parsed, expected)

    @given(epoch_ms=_epoch_millis)
    def test_epoch_millis_roundtrip(self, epoch_ms):
        rendered = str(epoch_ms)
        parsed = parse_catchup_timestamp(rendered)
        # normalize truncates to whole seconds (isoformat timespec="seconds").
        expected = datetime.fromtimestamp(epoch_ms // 1000, tz=timezone.utc).replace(
            tzinfo=None
        )
        self.assertEqual(parsed, expected)

    @given(digits=st.from_regex(r"\d{1,9}|\d{11,12}|\d{14,20}", fullmatch=True))
    def test_unsupported_digit_lengths_rejected(self, digits):
        # Only 10- or 13-digit all-digit strings are documented as epochs.
        self.assertIsNone(normalize_catchup_timestamp_input(digits))

    @given(value=_garbage)
    def test_parse_implies_normalize_and_back(self, value):
        # Whatever normalize emits must itself parse (idempotent pipeline).
        iso_value = normalize_catchup_timestamp_input(value)
        if iso_value is None:
            self.assertIsNone(parse_catchup_timestamp(value))
        else:
            reparsed = datetime.fromisoformat(iso_value)
            self.assertEqual(parse_catchup_timestamp(value), reparsed)


class ProviderTimezoneProperties(SimpleTestCase):
    @given(value=_garbage, tz=st.text(max_size=60))
    def test_never_raises_and_unparseable_returns_input(self, value, tz):
        result = convert_timestamp_to_provider_tz(value, tz)
        if parse_catchup_timestamp(value) is None:
            self.assertEqual(result, value)

    @given(dt=_valid_date_times, tz_name=st.sampled_from(
        ["Europe/Brussels", "America/New_York", "Asia/Tokyo", "Australia/Sydney"]
    ))
    def test_convert_then_parse_in_zone(self, dt, tz_name):
        from zoneinfo import ZoneInfo

        rendered = dt.strftime("%Y-%m-%d:%H-%M")
        converted = convert_timestamp_to_provider_tz(rendered, tz_name)
        parsed = parse_catchup_timestamp(converted)
        self.assertIsNotNone(parsed)
        expected = (
            dt.replace(second=0, microsecond=0, tzinfo=timezone.utc)
            .astimezone(ZoneInfo(tz_name))
            .replace(tzinfo=None)
        )
        self.assertEqual(parsed, expected)

    @given(dt=_valid_date_times)
    def test_utc_and_falsy_tz_are_identity(self, dt):
        rendered = dt.strftime("%Y-%m-%d:%H-%M")
        self.assertEqual(convert_timestamp_to_provider_tz(rendered, "UTC"), rendered)
        self.assertEqual(convert_timestamp_to_provider_tz(rendered, ""), rendered)
        self.assertEqual(convert_timestamp_to_provider_tz(rendered, None), rendered)


# ---------------------------------------------------------------------------
# Duration window helpers
# ---------------------------------------------------------------------------


class DurationWindowProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), _garbage, st.integers()))
    def test_client_duration_to_window_never_raises(self, value):
        client_duration_to_window(value)

    @given(minutes=st.integers(min_value=1, max_value=10**9))
    def test_positive_minutes_are_buffered_and_capped(self, minutes):
        window = client_duration_to_window(minutes)
        expected = min(minutes + DURATION_BUFFER_MINUTES, MAX_DURATION_MINUTES)
        self.assertEqual(window, expected)
        self.assertGreater(window, 0)
        self.assertLessEqual(window, MAX_DURATION_MINUTES)

    @given(value=st.one_of(
        st.integers(max_value=0),
        st.floats(allow_nan=True, allow_infinity=True),
        st.text(max_size=40),
    ))
    def test_non_positive_or_garbage_returns_none_or_valid_window(self, value):
        window = client_duration_to_window(value)
        if window is not None:
            self.assertGreater(window, 0)
            self.assertLessEqual(window, MAX_DURATION_MINUTES)


# ---------------------------------------------------------------------------
# programme_age_days
# ---------------------------------------------------------------------------


class ProgrammeAgeProperties(SimpleTestCase):
    @given(value=_garbage)
    def test_never_raises(self, value):
        programme_age_days(value)

    @given(dt=_valid_date_times)
    def test_age_bounds_against_now(self, dt):
        now = datetime(2026, 9, 11, 12, 0, 0)
        age = programme_age_days(dt.strftime("%Y-%m-%d %H:%M:%S"), now=now)
        elapsed_days = (now - dt).total_seconds() / 86400.0
        if elapsed_days <= 0:
            self.assertEqual(age, 0)
        else:
            self.assertGreaterEqual(age, 1)
            self.assertGreaterEqual(age, math.floor(elapsed_days))
            self.assertLessEqual(age, math.ceil(elapsed_days))

    @given(value=_garbage)
    def test_unparseable_returns_none(self, value):
        if parse_catchup_timestamp(value) is None:
            self.assertIsNone(programme_age_days(value))


# ---------------------------------------------------------------------------
# order_catchup_streams_for_timestamp
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, catchup_days):
        self.catchup_days = catchup_days


class OrderStreamsProperties(SimpleTestCase):
    @given(
        days_list=st.lists(
            st.one_of(st.integers(min_value=-5, max_value=30), st.none(), st.text(max_size=6)),
            max_size=12,
        )
    )
    def test_is_stable_permutation(self, days_list):
        streams = [_FakeStream(d) for d in days_list]
        ordered = order_catchup_streams_for_timestamp(
            streams, "2026-09-10:12-00", now=datetime(2026, 9, 11, 12, 0, 0)
        )
        # Same multiset, same length — nothing dropped or duplicated.
        self.assertEqual(len(ordered), len(streams))
        self.assertEqual(sorted(map(id, ordered)), sorted(map(id, streams)))

    @given(value=_garbage)
    def test_unparseable_timestamp_preserves_order(self, value):
        assume(parse_catchup_timestamp(value) is None)
        streams = [_FakeStream(d) for d in [0, 3, 7, None]]
        ordered = order_catchup_streams_for_timestamp(streams, value)
        self.assertEqual([id(s) for s in ordered], [id(s) for s in streams])


# ---------------------------------------------------------------------------
# Range / Content-Range header parsing
# ---------------------------------------------------------------------------


class RangeParsingProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), _garbage))
    def test_parse_client_range_never_raises(self, value):
        result = _parse_client_range(value)
        self.assertTrue(result is None or (isinstance(result, tuple) and len(result) == 2))

    @given(value=st.one_of(st.none(), _garbage))
    def test_parse_content_range_never_raises(self, value):
        _parse_content_range_header(value)

    @given(start=_non_negative_ints, end=st.one_of(st.none(), _non_negative_ints))
    def test_roundtrip_client_range(self, start, end):
        header = f"bytes={start}-" + ("" if end is None else str(end))
        parsed = _parse_client_range(header)
        self.assertEqual(parsed, (start, end))
        self.assertEqual(_parse_range_start(header), start)

    @given(start=_non_negative_ints, end=_non_negative_ints, total=st.one_of(st.none(), _non_negative_ints))
    def test_roundtrip_content_range(self, start, end, total):
        total_str = "*" if total is None else str(total)
        header = f"bytes {start}-{end}/{total_str}"
        parsed = _parse_content_range_header(header)
        self.assertEqual(parsed, {"start": start, "end": end, "total": total})

    @given(value=st.one_of(st.none(), _garbage))
    def test_is_full_restart_range_never_raises(self, value):
        _is_full_restart_range(value)

    @given(value=st.one_of(st.none(), _garbage), length=st.one_of(st.none(), _garbage, _non_negative_ints))
    def test_is_near_eof_probe_never_raises(self, value, length):
        _is_near_eof_probe(value, length)

    @given(start=_non_negative_ints)
    def test_cap_open_ended_range_caps_span(self, start):
        cap = 2_097_152
        capped = _cap_open_ended_range(f"bytes={start}-", cap)
        parsed = _parse_client_range(capped)
        self.assertEqual(parsed, (start, start + cap - 1))

    @given(header=st.one_of(st.none(), _garbage))
    def test_cap_open_ended_range_leaves_non_open_ended_unchanged(self, header):
        parsed = _parse_client_range(header)
        assume(parsed is None or parsed[1] is not None)
        self.assertEqual(_cap_open_ended_range(header, 1024), header)


# ---------------------------------------------------------------------------
# Stats position math
# ---------------------------------------------------------------------------


class StatsPositionProperties(SimpleTestCase):
    @given(
        range_start=st.one_of(st.none(), st.integers()),
        content_length=st.one_of(st.none(), _garbage, st.integers()),
        duration_secs=st.one_of(st.none(), _garbage, st.floats(allow_nan=True, allow_infinity=True)),
    )
    def test_byte_range_base_never_raises(self, range_start, content_length, duration_secs):
        # range_start mirrors the real caller (_parse_range_start): int or None.
        compute_playback_base_from_byte_range(range_start, content_length, duration_secs)

    @given(
        range_start=st.integers(min_value=1, max_value=10**12),
        content_length=st.integers(min_value=1, max_value=10**12),
        duration_secs=st.floats(min_value=0.001, max_value=10**6, allow_nan=False, allow_infinity=False),
    )
    def test_byte_range_base_within_programme(self, range_start, content_length, duration_secs):
        base = compute_playback_base_from_byte_range(range_start, content_length, duration_secs)
        self.assertIsNotNone(base)
        self.assertGreaterEqual(base, 0.0)
        self.assertLessEqual(base, duration_secs)

    @given(
        position_anchor=st.one_of(st.none(), _garbage, st.floats(allow_nan=True, allow_infinity=True)),
        current_time=st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10**12),
        playback_base=st.one_of(st.none(), _garbage, st.floats(allow_nan=True, allow_infinity=True)),
        paused=st.booleans(),
        duration=st.one_of(st.none(), st.floats(min_value=0.001, max_value=10**6, allow_nan=False)),
    )
    def test_playback_position_never_raises_with_byte_base(
        self, position_anchor, current_time, playback_base, paused, duration
    ):
        # The playback_base path does not touch the timestamp/EPG strings, so
        # arbitrary garbage there must still be safe.
        compute_playback_position_secs(
            "garbage",
            "not-an-iso-date",
            position_anchor,
            current_time,
            duration_secs=duration,
            playback_base_secs=playback_base,
            paused=paused,
        )

    @given(
        offset_secs=st.integers(min_value=0, max_value=7200),
        anchor_age_secs=st.floats(min_value=0, max_value=7200, allow_nan=False),
        duration=st.one_of(st.none(), st.floats(min_value=1, max_value=10**6, allow_nan=False)),
        paused=st.booleans(),
    )
    def test_playback_position_within_bounds(
        self, offset_secs, anchor_age_secs, duration, paused
    ):
        # Integer offsets: the XC URL shapes only carry whole seconds, so a
        # fractional playhead would be truncated by the strftime round-trip.
        epg_start = datetime(2026, 9, 11, 10, 0, 0)
        url_start = epg_start + timedelta(seconds=offset_secs)
        now = 1_800_000_000.0
        anchor = now - anchor_age_secs
        position = compute_playback_position_secs(
            url_start.strftime("%Y-%m-%d:%H-%M"),
            epg_start.isoformat(),
            anchor,
            now,
            duration_secs=duration,
            playback_base_secs=None,
            paused=paused,
        )
        self.assertIsNotNone(position)
        self.assertGreaterEqual(position, 0.0)
        if duration:
            self.assertLessEqual(position, duration)
        if paused:
            # Paused freezes the playhead at the URL offset. The XC URL shape
            # only carries whole minutes (strftime "%Y-%m-%d:%H-%M"), so the
            # effective offset is truncated to the minute.
            url_offset = (offset_secs // 60) * 60
            self.assertAlmostEqual(
                position, min(url_offset, duration) if duration else url_offset, places=3
            )

    @given(value=st.one_of(
        st.none(),
        _garbage,
        # Bytes are in-contract (Redis hashes), but only UTF-8 ones: the paused
        # field is written by Dispatcharr itself as an ASCII flag, and the whole
        # decode path (_decode_hash) shares that assumption.
        st.binary(max_size=40).filter(lambda b: _is_utf8(b)),
    ))
    def test_client_paused_never_raises_and_truthy_set(self, value):
        result = _client_paused(value)
        self.assertIn(result, (True, False))
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}:
            self.assertTrue(result)


# ---------------------------------------------------------------------------
# Provider URL builders
# ---------------------------------------------------------------------------


class UrlBuilderProperties(SimpleTestCase):
    @given(
        stream_id=st.one_of(_garbage, st.integers()),
        timestamp=st.one_of(_garbage,),
        duration=st.one_of(_garbage, st.integers()),
    )
    def test_builders_never_raise(self, stream_id, timestamp, duration):
        build_timeshift_url_format_a(_creds(), stream_id, timestamp, duration)
        build_timeshift_url_format_b(_creds(), stream_id, timestamp, duration)
        build_timeshift_candidate_urls(_creds(), stream_id, timestamp, duration)

    @given(dt=_valid_date_times, duration=st.integers(min_value=1, max_value=480))
    def test_candidate_order_path_before_query(self, dt, duration):
        candidates = build_timeshift_candidate_urls(
            _creds(), 42, dt.strftime("%Y-%m-%d:%H-%M"), duration
        )
        self.assertEqual(len(candidates), 7)
        path_kinds = ["timeshift.php" in url for url in candidates]
        # Every PATH candidate (no timeshift.php) precedes every QUERY one.
        self.assertEqual(path_kinds, sorted(path_kinds))

    @given(credentials=st.tuples(_garbage, _garbage))
    def test_credentials_are_url_quoted(self, credentials):
        username, password = credentials
        assume(".." not in username and ".." not in password)
        creds = TimeshiftCredentials("http://example.test", username, password)
        url = build_timeshift_url_format_b(creds, 1, "2026-09-10:12-00", 60)
        path_part = url.split("/timeshift/", 1)[1]
        segments = path_part.split("/")
        # Neither credential may smuggle extra path segments into the URL.
        self.assertEqual(len(segments), 5)
        self.assertNotIn("/", segments[0])
        self.assertNotIn("/", segments[1])


# ---------------------------------------------------------------------------
# Downstream length headers / presentation mapping
# ---------------------------------------------------------------------------


class DownstreamHeaderProperties(SimpleTestCase):
    @given(
        range_header=st.one_of(st.none(), _garbage),
        status=st.sampled_from([200, 206, 302, 416, 503]),
        rep_length=st.one_of(st.none(), _non_negative_ints),
        upstream_cr=st.one_of(st.none(), _garbage),
        upstream_cl=st.one_of(st.none(), _garbage),
        streaming=st.booleans(),
    )
    def test_build_downstream_headers_never_raises(
        self, range_header, status, rep_length, upstream_cr, upstream_cl, streaming
    ):
        headers = _build_downstream_length_headers(
            range_header=range_header,
            status_code=status,
            representation_length=rep_length,
            upstream_content_range=upstream_cr,
            upstream_content_length=upstream_cl,
            streaming=streaming,
        )
        self.assertEqual(headers["Accept-Ranges"], "bytes")

    @given(
        start=_non_negative_ints,
        end=_non_negative_ints,
        total=st.one_of(st.none(), _non_negative_ints),
    )
    def test_206_forwards_upstream_content_range_verbatim(self, start, end, total):
        total_str = "*" if total is None else str(total)
        upstream_cr = f"bytes {start}-{end}/{total_str}"
        headers = _build_downstream_length_headers(
            range_header=f"bytes={start}-{end}",
            status_code=206,
            representation_length=total,
            upstream_content_range=upstream_cr,
            upstream_content_length=None,
        )
        self.assertEqual(headers["Content-Range"], upstream_cr)

    @given(length=st.one_of(_non_negative_ints))
    def test_plain_streaming_200_sets_content_length(self, length):
        headers = _build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=length,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=True,
        )
        self.assertEqual(headers["Content-Length"], str(length))


class PresentationMappingProperties(SimpleTestCase):
    @given(
        header=st.one_of(st.none(), _garbage),
        base=st.one_of(st.none(), _garbage, _non_negative_ints),
    )
    def test_map_client_range_never_raises(self, header, base):
        _map_client_range_through_presentation(header, base)

    @given(
        start=_non_negative_ints,
        end=st.one_of(st.none(), _non_negative_ints),
        base=_non_negative_ints,
    )
    def test_map_client_range_shifts_by_base(self, start, end, base):
        header = f"bytes={start}-" + ("" if end is None else str(end))
        mapped = _map_client_range_through_presentation(header, base)
        parsed = _parse_client_range(mapped)
        self.assertEqual(
            parsed, (base + start, None if end is None else base + end)
        )

    @given(
        cr=st.one_of(st.none(), _garbage),
        base=st.one_of(st.none(), _garbage, _non_negative_ints),
        length=st.one_of(st.none(), _garbage, _non_negative_ints),
    )
    def test_presentation_relative_content_range_never_raises(self, cr, base, length):
        _presentation_relative_content_range(
            cr, presentation_byte_base=base, presentation_length=length
        )

    @given(
        start=st.integers(min_value=0, max_value=10**9),
        span=st.integers(min_value=0, max_value=10**6),
        base=st.integers(min_value=0, max_value=10**9),
        length=st.integers(min_value=0, max_value=2 * 10**9),
    )
    def test_presentation_relative_roundtrip(self, start, span, base, length):
        abs_start = base + start
        abs_end = abs_start + span
        cr = f"bytes {abs_start}-{abs_end}/*"
        rel = _presentation_relative_content_range(
            cr, presentation_byte_base=base, presentation_length=length
        )
        self.assertEqual(rel, f"bytes {start}-{abs_end - base}/{length}")


class PoolIntFieldProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), _garbage, st.binary(max_size=40), st.integers()))
    def test_never_raises(self, value):
        _pool_int_field(value)

    @given(value=st.integers())
    def test_roundtrip_int_and_str_and_bytes(self, value):
        self.assertEqual(_pool_int_field(value), value)
        self.assertEqual(_pool_int_field(str(value)), value)
        self.assertEqual(_pool_int_field(str(value).encode()), value)

    @given(value=_garbage)
    def test_non_numeric_returns_none(self, value):
        assume(not value.strip().lstrip("+-").isdigit())
        self.assertIsNone(_pool_int_field(value))


# ---------------------------------------------------------------------------
# resolve_stats_playback_fields
# ---------------------------------------------------------------------------


class ResolveStatsPlaybackProperties(SimpleTestCase):
    @given(
        timestamp=st.one_of(_garbage,),
        existing_start=st.one_of(st.none(), _garbage, st.binary(max_size=40).filter(_is_utf8)),
        existing_anchor=st.one_of(st.none(), _garbage, st.binary(max_size=40).filter(_is_utf8)),
        existing_base=st.one_of(st.none(), _garbage, st.binary(max_size=40).filter(_is_utf8)),
        range_start=st.one_of(st.none(), st.integers()),
        rep_length=st.one_of(st.none(), st.integers()),
        duration=st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True), _garbage),
        now=st.floats(min_value=0, max_value=10**12, allow_nan=False),
    )
    def test_never_raises(
        self, timestamp, existing_start, existing_anchor, existing_base,
        range_start, rep_length, duration, now,
    ):
        result = resolve_stats_playback_fields(
            timestamp_utc=timestamp,
            existing_programme_start=existing_start,
            existing_position_anchor=existing_anchor,
            existing_playback_base=existing_base,
            range_start=range_start,
            representation_length=rep_length,
            programme_duration_secs=duration,
            now=now,
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @given(
        range_start=st.integers(min_value=1, max_value=10**9),
        rep_length=st.integers(min_value=1, max_value=10**9),
        duration=st.floats(min_value=1, max_value=10**6, allow_nan=False),
        now=st.floats(min_value=0, max_value=10**12, allow_nan=False),
    )
    def test_byte_seek_anchors_at_now(self, range_start, rep_length, duration, now):
        # Mid-file byte seek on the same programme reanchors wall-clock at now
        # and carries the mapped byte base.
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-09-11:10-00",
            existing_programme_start="2026-09-11:10-00",
            existing_position_anchor=None,
            existing_playback_base=None,
            range_start=range_start,
            representation_length=rep_length,
            programme_duration_secs=duration,
            now=now,
        )
        # Skip near-EOF probe territory, which intentionally keeps old anchor.
        if range_start >= max(0, rep_length - EOF_PROBE_TAIL_BYTES):
            return
        self.assertEqual(anchor, now)
        self.assertIsNotNone(base)
        self.assertGreaterEqual(base, 0.0)
        self.assertLessEqual(base, duration)

    @given(
        rep_length=st.integers(min_value=1, max_value=10**9),
        now=st.floats(min_value=0, max_value=10**12, allow_nan=False),
        existing_base=st.one_of(st.none(), st.floats(min_value=0, max_value=10**6, allow_nan=False)),
    )
    def test_near_eof_probe_keeps_existing_anchor(self, rep_length, now, existing_base):
        # A probe in the last EOF_PROBE_TAIL_BYTES must not reanchor stats.
        range_start = max(0, rep_length - EOF_PROBE_TAIL_BYTES) + 1
        if range_start >= rep_length:
            range_start = rep_length
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-09-11:10-00",
            existing_programme_start="2026-09-11:10-00",
            existing_position_anchor="12345.0",
            existing_playback_base=(
                None if existing_base is None else str(existing_base)
            ),
            range_start=range_start,
            representation_length=rep_length,
            programme_duration_secs=3600.0,
            now=now,
        )
        self.assertEqual(anchor, "12345.0")
        if existing_base is None:
            self.assertIsNone(base)
        else:
            self.assertAlmostEqual(base, existing_base, places=6)


# ---------------------------------------------------------------------------
# parse_stats_channel_id
# ---------------------------------------------------------------------------


class StatsChannelIdProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), _garbage, st.integers()))
    def test_never_raises(self, value):
        parse_stats_channel_id(value)

    @given(
        channel_id=st.integers(min_value=0, max_value=2**63),
        session=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=1, max_size=40),
    )
    def test_roundtrip(self, channel_id, session):
        assume("_" not in session or True)  # session may itself contain "_"
        stats_id = f"{channel_id}_{session}"
        parsed = parse_stats_channel_id(stats_id)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["channel_id"], channel_id)
        self.assertEqual(parsed["session_id"], session)

    @given(value=_garbage)
    def test_no_digits_before_underscore_returns_none(self, value):
        if not re.match(r"^\d+_.+$", value):
            self.assertIsNone(parse_stats_channel_id(value))
