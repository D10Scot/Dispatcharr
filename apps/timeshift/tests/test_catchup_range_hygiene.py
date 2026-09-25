"""Catch-up Range and timestamp hygiene: #216, #141, #111 and #491.

Each test is named for the defect it pins. The #141 and #216 inputs are the
shrunk counterexamples from the issue bodies, kept verbatim.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.timeshift import views
from apps.timeshift.helpers import (
    build_timeshift_candidate_urls,
    convert_timestamp_to_provider_tz,
)
from apps.timeshift.stats import (
    EOF_PROBE_TAIL_BYTES,
    is_near_eof_offset,
    resolve_stats_playback_fields,
)


class SmallArchiveEofProbeTests(SimpleTestCase):
    """#216: an archive no larger than the tail window has no tail to probe."""

    SMALL = 1_572_864  # 1.5 MiB, from the issue's harness

    def test_a_mid_file_seek_on_a_small_archive_was_classified_as_an_eof_probe(self):
        for start in (512_000, 1_048_576):
            with self.subTest(start=start):
                self.assertFalse(views._is_near_eof_probe(f"bytes={start}-", self.SMALL))
                self.assertTrue(
                    views._should_displace_busy_playback(f"bytes={start}-", self.SMALL, "bytes=0-")
                )

    def test_the_window_boundary(self):
        self.assertFalse(is_near_eof_offset(0, EOF_PROBE_TAIL_BYTES))
        total = EOF_PROBE_TAIL_BYTES + 1
        self.assertFalse(is_near_eof_offset(0, total))
        self.assertTrue(is_near_eof_offset(1, total))

    def test_a_large_archive_tail_is_still_an_eof_probe(self):
        total = 104_857_600
        self.assertTrue(views._is_near_eof_probe(f"bytes={total - 1000}-", total))

    def test_a_small_archive_seek_kept_the_previous_stats_base(self):
        base, _anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-06-08:17-00",
            existing_programme_start="2026-06-08:17-00",
            existing_position_anchor=100.0,
            existing_playback_base="5.0",
            range_start=786_432,
            representation_length=self.SMALL,
            programme_duration_secs=600.0,
            now=200.0,
        )
        self.assertNotEqual(base, 5.0)


class CatchupRangeHeaderTests(SimpleTestCase):
    """#141: no invalid Content-Range and no negative Content-Length."""

    def test_a_suffix_range_was_parsed_as_a_prefix(self):
        self.assertIsNone(views._parse_client_range("bytes=-500"))
        self.assertTrue(views._is_near_eof_probe("bytes=-500", None))

    def test_a_suffix_range_was_widened_through_the_presentation_base(self):
        self.assertEqual(views._map_client_range_through_presentation("bytes=-500", 50), "bytes=-500")

    def test_an_inverted_client_range_was_accepted(self):
        self.assertIsNone(views._parse_client_range("bytes=100-50"))
        headers = views._build_downstream_length_headers(
            range_header="bytes=100-50", status_code=206, representation_length=100,
            upstream_content_range=None, upstream_content_length=None,
        )
        self.assertNotIn("Content-Range", headers)

    def test_a_start_beyond_eof_synthesised_an_inverted_content_range(self):
        headers = views._build_downstream_length_headers(
            range_header="bytes=5000-", status_code=206, representation_length=100,
            upstream_content_range=None, upstream_content_length=None,
        )
        self.assertNotIn("Content-Range", headers)

    def test_an_inverted_upstream_content_range_gave_a_negative_content_length(self):
        self.assertIsNone(views._parse_content_range_header("bytes 100-50/1000"))
        headers = views._build_downstream_length_headers(
            range_header="bytes=0-", status_code=206, representation_length=1000,
            upstream_content_range="bytes 100-50/1000", upstream_content_length=None,
        )
        self.assertNotEqual(headers.get("Content-Range"), "bytes 100-50/1000")
        self.assertFalse(str(headers.get("Content-Length", "0")).startswith("-"))

    def test_an_untranslatable_upstream_range_leaked_absolute_coordinates(self):
        self.assertIsNone(
            views._presentation_relative_content_range(
                "bytes 400-499/1000", presentation_byte_base=500, presentation_length=100,
            )
        )


    def test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int(self):
        # "²".isdigit() is True and int("²") raises. The seed's
        # try/except int() returned None for these; the stricter parsers must too.
        for header in ("bytes=²-", "bytes=0-²"):
            with self.subTest(header=header):
                self.assertIsNone(views._parse_client_range(header))
        self.assertFalse(views._is_suffix_range("bytes=-²"))
        # "٣" is isdecimal() and int() accepts it (the seed parsed
        # bytes=٣- as (3, None)); RFC 9110 allows ASCII DIGIT only.
        self.assertIsNone(views._parse_client_range("bytes=٣-"))
        self.assertIsNone(views._parse_content_range_header("bytes ٣-5/10"))
        self.assertFalse(views._is_near_eof_probe("bytes=-²", None))
        for value in ("bytes ²-5/10", "bytes 0-³/10", "bytes 0-5/¹"):
            with self.subTest(value=value):
                self.assertIsNone(views._parse_content_range_header(value))


class ProviderTimezoneSecondsTests(SimpleTestCase):
    """#111: a non-UTC provider zone must not drop the requested seconds."""

    def test_a_non_utc_provider_zone_truncated_the_start_to_the_minute(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-01-15:12-00-45", "Europe/Brussels"),
            "2026-01-15:13-00-45",
        )

    def test_the_colon_seconds_candidate_keeps_the_seconds_in_every_zone(self):
        from types import SimpleNamespace

        creds = SimpleNamespace(server_url="http://p.example", username="u", password="p")
        for zone, expected in (("UTC", "2026-01-15:12:00:45"), ("Europe/Brussels", "2026-01-15:13:00:45")):
            with self.subTest(zone=zone):
                ts = convert_timestamp_to_provider_tz("2026-01-15:12-00-45", zone)
                self.assertIn(f"/{expected}/", build_timeshift_candidate_urls(creds, "1", ts, 60)[2])

    def test_a_minute_precision_start_keeps_its_minute_shape(self):
        # The redirect URL is built from this value verbatim; a request with
        # no seconds must not grow a ":00" it never asked for.
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-01-15:12-00", "Europe/Brussels"),
            "2026-01-15:13-00",
        )

    def test_seconds_survive_a_provider_zone_dst_boundary(self):
        # The fix keys off local_dt.second, which is unaffected by which side
        # of a DST transition the converted instant lands on; every 2026
        # Brussels offset is a whole number of minutes. Confirmed on both
        # sides of the 2026-03-29 Europe/Brussels spring-forward (01:00 UTC).
        for utc_input, expected in (
            ("2026-03-29:00-59-59", "2026-03-29:01-59-59"),  # CET, before
            ("2026-03-29:01-00-30", "2026-03-29:03-00-30"),  # CEST, after
        ):
            with self.subTest(utc_input=utc_input):
                self.assertEqual(
                    convert_timestamp_to_provider_tz(utc_input, "Europe/Brussels"),
                    expected,
                )


class ProviderContentLengthHygieneTests(SimpleTestCase):
    """#491: a provider Content-Length of "-1" or "0" was forwarded verbatim.

    ``_extract_representation_length``'s old ``if content_length:`` check
    treated both as truthy (int("-1") == -1, int("0") == 0), and even after
    that helper returned None, ``_build_downstream_length_headers``'s raw
    ``elif upstream_content_length:`` fallback on the plain streaming 200
    branch put the untouched header text straight on the response. A client
    receiving ``Content-Length: -1`` treats it as malformed.
    """

    def _upstream(self, content_length=None, content_range=None):
        headers = {}
        if content_length is not None:
            headers["Content-Length"] = content_length
        if content_range is not None:
            headers["Content-Range"] = content_range
        return SimpleNamespace(headers=headers)

    def test_a_negative_content_length_on_a_plain_streaming_200_was_forwarded(self):
        upstream = self._upstream(content_length="-1")
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=views._extract_representation_length(upstream),
            upstream_content_range=upstream.headers.get("Content-Range"),
            upstream_content_length=upstream.headers.get("Content-Length"),
            streaming=True,
        )
        self.assertNotIn("Content-Length", headers)

    def test_a_zero_content_length_on_a_plain_streaming_200_was_forwarded(self):
        upstream = self._upstream(content_length="0")
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=views._extract_representation_length(upstream),
            upstream_content_range=upstream.headers.get("Content-Range"),
            upstream_content_length=upstream.headers.get("Content-Length"),
            streaming=True,
        )
        self.assertNotIn("Content-Length", headers)

    def test_a_positive_content_length_on_a_plain_streaming_200_is_still_advertised(self):
        upstream = self._upstream(content_length="12345")
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=views._extract_representation_length(upstream),
            upstream_content_range=upstream.headers.get("Content-Range"),
            upstream_content_length=upstream.headers.get("Content-Length"),
            streaming=True,
        )
        self.assertEqual(headers.get("Content-Length"), "12345")

    def test_a_zero_content_length_on_a_non_streaming_answer_is_a_genuinely_empty_body(self):
        # Only the non-streaming path (no long-lived stream to preempt with a
        # seek) may advertise a "0" -- the issue's own carve-out.
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=None,
            upstream_content_range=None,
            upstream_content_length="0",
            streaming=False,
        )
        self.assertEqual(headers.get("Content-Length"), "0")

    def test_extract_representation_length_treats_non_positive_or_non_digit_as_absent(self):
        for content_length in ("-1", "0", "²"):
            with self.subTest(content_length=content_length):
                self.assertIsNone(
                    views._extract_representation_length(
                        self._upstream(content_length=content_length)
                    )
                )
        self.assertEqual(
            views._extract_representation_length(self._upstream(content_length="1234")),
            1234,
        )

    def test_a_stale_pool_cache_representation_length_of_negative_one_was_forwarded(self):
        # #491 round 2: a pre-fix process could have cached
        # _extract_representation_length's old int("-1") == -1 result in the
        # Redis pool `content_length` hash (views.py ~:3393). A cached value
        # reaches the builder as representation_length directly, bypassing
        # upstream_content_length's own sanitization entirely.
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=-1,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=True,
        )
        self.assertNotIn("Content-Length", headers)

    def test_a_zero_representation_length_on_a_plain_streaming_200_was_forwarded(self):
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=0,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=True,
        )
        self.assertNotIn("Content-Length", headers)

    def test_a_zero_representation_length_on_a_non_streaming_answer_is_kept(self):
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=0,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=False,
        )
        self.assertEqual(headers.get("Content-Length"), "0")
