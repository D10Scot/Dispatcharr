"""apps/proxy/vod_proxy/byte_range.py: the arithmetic behind #64, #66 and #98."""

from django.test import SimpleTestCase

from apps.proxy.vod_proxy.byte_range import (
    UNSATISFIABLE,
    parse_content_range,
    parse_length,
    plan_downstream,
    resolve_range,
    slice_chunks,
)


class ResolveRangeTests(SimpleTestCase):
    def test_a_suffix_range_was_resolved_as_a_prefix(self):
        # #64: bytes=-500 is the LAST 500 bytes, never bytes=0-500.
        self.assertEqual(resolve_range("bytes=-500", 10_000), (9_500, 9_999))

    def test_a_suffix_longer_than_the_file_is_the_whole_file(self):
        self.assertEqual(resolve_range("bytes=-500", 100), (0, 99))

    def test_a_zero_length_suffix_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=-0", 100), UNSATISFIABLE)

    def test_open_and_closed_ranges(self):
        self.assertEqual(resolve_range("bytes=100-", 1000), (100, 999))
        self.assertEqual(resolve_range("bytes=100-199", 1000), (100, 199))
        self.assertEqual(resolve_range("bytes=100-5000", 1000), (100, 999))

    def test_a_start_at_or_past_the_end_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=1000-", 1000), UNSATISFIABLE)
        self.assertIs(resolve_range("bytes=99999999-", 1000), UNSATISFIABLE)

    def test_an_inverted_range_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=200-100", 1000), UNSATISFIABLE)

    def test_ranges_this_proxy_does_not_understand_are_ignored(self):
        for header in (None, "", "items=0-1", "bytes=0-1,5-9", "bytes=abc-", "bytes=5"):
            with self.subTest(header=header):
                self.assertIsNone(resolve_range(header, 1000))


class NonAsciiDigitTests(SimpleTestCase):
    """"²".isdigit() is True and int("²") raises; WSGI decodes headers
    as Latin-1, so a bare isdigit() guard turns these headers into a 500."""

    def test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int(self):
        for header in ("bytes=²-", "bytes=0-²", "bytes=-²"):
            with self.subTest(header=header):
                self.assertIsNone(resolve_range(header, 1000))
        for value in ("bytes ²-5/10", "bytes 0-³/10", "bytes 0-5/¹"):
            with self.subTest(value=value):
                self.assertIsNone(parse_content_range(value))
        self.assertIsNone(parse_length("²"))
        # "٣" (Arabic-Indic three) is isdecimal() and int() ACCEPTS it, so it
        # does not crash; it is still not the ASCII DIGIT RFC 9110 allows.
        self.assertIsNone(resolve_range("bytes=٣-", 1000))
        self.assertIsNone(parse_content_range("bytes ٣-5/10"))
        self.assertIsNone(plan_downstream(None, 200, None, "²", None).content_length)


class ParseContentRangeTests(SimpleTestCase):
    def test_valid(self):
        self.assertEqual(parse_content_range("bytes 0-99/1000"), (0, 99, 1000))
        self.assertEqual(parse_content_range("bytes 0-99/*"), (0, 99, None))

    def test_invalid_values_are_refused(self):
        for value in (None, "", "bytes */1000", "bytes 100-50/1000", "bytes 0-1000/1000", "bytes x-1/2"):
            with self.subTest(value=value):
                self.assertIsNone(parse_content_range(value))


class PlanDownstreamTests(SimpleTestCase):
    def test_a_range_ignoring_provider_was_trusted_as_a_206(self):
        # #66: the provider sent the whole file with a 200; cut it.
        plan = plan_downstream("bytes=100-199", 200, None, "1000", 1000)
        self.assertEqual((plan.status, plan.content_range, plan.content_length), (206, "bytes 100-199/1000", 100))
        self.assertEqual((plan.skip, plan.limit), (100, 100))

    def test_a_provider_206_is_relayed_as_sent(self):
        plan = plan_downstream("bytes=-100", 206, "bytes 900-999/1000", "100", None)
        self.assertEqual((plan.status, plan.content_range, plan.content_length, plan.skip), (206, "bytes 900-999/1000", 100, 0))

    def test_an_unsatisfiable_range_against_a_whole_body_is_416(self):
        self.assertTrue(plan_downstream("bytes=5000-", 200, None, "1000", None).unsatisfiable)

    def test_no_client_range_is_a_200(self):
        plan = plan_downstream(None, 200, None, "1000", 1000)
        self.assertEqual((plan.status, plan.content_length, plan.content_range), (200, 1000, None))


class SliceChunksTests(SimpleTestCase):
    def test_slices_across_chunk_boundaries(self):
        data = bytes(range(100))
        chunks = [data[i:i + 7] for i in range(0, 100, 7)]
        self.assertEqual(b"".join(slice_chunks(chunks, 10, 20)), data[10:30])
        self.assertEqual(b"".join(slice_chunks(chunks, 0, None)), data)
        self.assertEqual(b"".join(slice_chunks(chunks, 95, None)), data[95:])
