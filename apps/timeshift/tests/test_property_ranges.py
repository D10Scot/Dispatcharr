"""Property tests for the catch-up HTTP Range / Content-Range helpers.

Written against the contracts PR D-3 (#141, #216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9; D-3 moves them by a few lines), all in
apps/timeshift/views.py unless named:

- ``_parse_client_range`` (:1111) and ``_parse_range_start`` (:1103): RFC 9110
  ``bytes=a-`` / ``bytes=a-b`` only. The suffix form ``bytes=-N`` and an inverted
  ``b < a`` are None (#141). ``_is_suffix_range`` is new in D-3.
- ``_parse_content_range_header`` (:1131): ``bytes a-b/T`` with ``a <= b`` and
  ``b < T`` (or ``T == '*'``), else None (#141).
- ``_extract_representation_length`` (:1151) and ``_build_downstream_length_headers``
  (:1169): never a negative Content-Length, and never an unsatisfiable Content-Range
  (#141).
- ``_is_near_eof_probe`` (:1230) and ``is_near_eof_offset`` (apps/timeshift/stats.py,
  new in D-3): an archive no larger than the probe window has no tail (#216), and a
  suffix range is a tail probe by definition (#141).
- ``_cap_open_ended_range`` (:1353) and ``_is_full_restart_range`` (:1303).
- ``_map_client_range_through_presentation`` (:1946) and
  ``_presentation_relative_content_range`` (:1961): translation by the presentation
  byte base, and never the absolute CDN range beside a presentation length (#141).

Every parser consumes remote input: the client's ``Range`` header and the provider's
``Content-Range``, both Latin-1 text under WSGI and requests. Hence the ``²``
examples: ``'²'.isdigit()`` is True but ``int('²')`` raises.

Closes the Range scope of #192 (survivor), #142, #215 and #260.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.timeshift import stats as ts_stats
from apps.timeshift import views as ts_views

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_stats.EOF_PROBE_TAIL_BYTES
UNKNOWN_LENGTH_MIN = ts_views._EOF_PROBE_UNKNOWN_LENGTH_MIN

offsets = st.integers(min_value=0, max_value=10**12)
# Header text a client or provider could send: arbitrary Latin-1 text, and the
# structural alphabet with the digit look-alikes that break isdigit()-based parsing.
header_text = (
    st.text(alphabet=st.characters(max_codepoint=0xFF), max_size=40)
    | st.text(alphabet="0123456789-/*, =bytes²³¹\t", max_size=30)
)
client_range_text = header_text | header_text.map(lambda s: "bytes=" + s)
content_range_text = header_text | header_text.map(lambda s: "bytes " + s)


def _satisfiable_client_range(parsed):
    start, end = parsed
    return isinstance(start, int) and start >= 0 and (end is None or end >= start)


class ClientRangeParserProperties(SimpleTestCase):
    @given(header=st.none() | client_range_text)
    # #141: a suffix and an inverted range were both returned as (start, end) pairs.
    @example(header="bytes=-500")
    @example(header="bytes=100-50")
    # isdigit() accepts Latin-1 superscripts that int() refuses (plan I, D-3 seam).
    @example(header="bytes=²-")
    @example(header="bytes=0-²")
    @example(header="bytes=--5")
    def test_parse_client_range_is_none_or_a_satisfiable_pair_for_any_header(self, header):
        parsed = ts_views._parse_client_range(header)
        if parsed is not None:
            self.assertTrue(_satisfiable_client_range(parsed), (header, parsed))
            self.assertEqual(ts_views._parse_range_start(header), parsed[0])
        else:
            self.assertIsNone(ts_views._parse_range_start(header))

    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9))
    def test_well_formed_range_specs_round_trip(self, start, length):
        if length is None:
            header, expected = f"bytes={start}-", (start, None)
        else:
            header, expected = f"bytes={start}-{start + length}", (start, start + length)
        self.assertEqual(ts_views._parse_client_range(header), expected)

    @given(n=st.integers(min_value=1, max_value=10**9))
    @example(n=500)  # #141's counterexample
    def test_suffix_range_is_not_parsed_as_a_prefix(self, n):
        header = f"bytes=-{n}"
        self.assertIsNone(ts_views._parse_client_range(header))
        self.assertTrue(ts_views._is_suffix_range(header))

    @given(end=offsets, gap=st.integers(min_value=1, max_value=10**6))
    @example(end=50, gap=50)  # #141: bytes=100-50
    def test_inverted_range_is_rejected(self, end, gap):
        self.assertIsNone(ts_views._parse_client_range(f"bytes={end + gap}-{end}"))

    @given(header=st.none() | client_range_text)
    @example(header="bytes=-²")
    @example(header="bytes=-0")
    def test_is_suffix_range_holds_exactly_for_bytes_dash_positive_ascii_n(self, header):
        tail = header[len("bytes=-"):] if header and header.startswith("bytes=-") else None
        expected = (
            tail is not None and tail.isascii() and tail.isdigit() and int(tail) > 0
        )
        self.assertEqual(ts_views._is_suffix_range(header), expected)


class ContentRangeParserProperties(SimpleTestCase):
    @given(value=st.none() | content_range_text)
    # #141: an inverted upstream Content-Range was accepted and later produced
    # Content-Length: -49.
    @example(value="bytes 100-50/1000")
    @example(value="bytes 0-10/10")
    @example(value="bytes ²-5/10")
    @example(value="bytes 0-5/²")
    def test_content_range_is_none_or_a_satisfiable_range(self, value):
        parsed = ts_views._parse_content_range_header(value)
        if parsed is None:
            return
        self.assertLessEqual(0, parsed["start"])
        self.assertLessEqual(parsed["start"], parsed["end"])
        if parsed["total"] is not None:
            self.assertLess(parsed["end"], parsed["total"])

    @given(start=offsets, length=st.integers(min_value=1, max_value=10**9),
           slack=st.none() | st.integers(min_value=0, max_value=10**9))
    def test_well_formed_content_range_round_trips(self, start, length, slack):
        end = start + length - 1
        total = None if slack is None else end + 1 + slack
        value = f"bytes {start}-{end}/{'*' if total is None else total}"
        self.assertEqual(
            ts_views._parse_content_range_header(value),
            {"start": start, "end": end, "total": total},
        )

    @given(content_range=st.none() | content_range_text,
           content_length=st.none() | st.text(max_size=12)
           | st.integers(min_value=0, max_value=10**12).map(str))
    # "0" and "-1" are truthy strings, so _extract_representation_length's
    # ``if content_length:`` check does not treat them as absent: it returns
    # int("0") == 0 and int("-1") == -1 respectively (views.py, near :1151).
    # Pinned explicitly rather than left to the derandomized draw: "0" is a
    # likely boundary value from the integers() branch, but "-1" is reachable
    # only through the free-text branch and is not guaranteed to be drawn in
    # 200 examples (review round 1).
    @example(content_range=None, content_length="0")
    @example(content_range=None, content_length="-1")
    def test_representation_length_prefers_the_content_range_total(
        self, content_range, content_length,
    ):
        headers = {}
        if content_range is not None:
            headers["Content-Range"] = content_range
        if content_length is not None:
            headers["Content-Length"] = content_length
        response = SimpleNamespace(headers=headers)
        result = ts_views._extract_representation_length(response)
        parsed = ts_views._parse_content_range_header(content_range or "")
        if parsed and parsed["total"] is not None:
            self.assertEqual(result, parsed["total"])
        elif content_length:
            try:
                expected = int(content_length)
            except ValueError:
                expected = None
            self.assertEqual(result, expected)
        else:
            self.assertIsNone(result)
        self.assertIsNone(ts_views._extract_representation_length(None))


class DownstreamHeaderProperties(SimpleTestCase):
    @given(
        range_header=st.none() | client_range_text,
        status_code=st.sampled_from([200, 206]),
        representation_length=st.none() | st.integers(min_value=0, max_value=10**10),
        upstream_content_range=st.none() | content_range_text,
        upstream_content_length=st.none() | st.integers(min_value=1, max_value=10**10),
        streaming=st.booleans(),
    )
    # #141: an inverted client range, a start past EOF, and an inverted upstream range.
    @example(range_header="bytes=100-50", status_code=206, representation_length=100,
             upstream_content_range=None, upstream_content_length=None, streaming=True)
    @example(range_header="bytes=5000-", status_code=206, representation_length=100,
             upstream_content_range=None, upstream_content_length=None, streaming=True)
    @example(range_header="bytes=0-", status_code=206, representation_length=None,
             upstream_content_range="bytes 100-50/1000", upstream_content_length=None,
             streaming=True)
    def test_headers_never_carry_an_unsatisfiable_range_or_a_negative_length(
        self, range_header, status_code, representation_length,
        upstream_content_range, upstream_content_length, streaming,
    ):
        headers = ts_views._build_downstream_length_headers(
            range_header=range_header,
            status_code=status_code,
            representation_length=representation_length,
            upstream_content_range=upstream_content_range,
            upstream_content_length=upstream_content_length,
            streaming=streaming,
        )
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        if "Content-Length" in headers:
            self.assertGreaterEqual(int(headers["Content-Length"]), 0, headers)
        if "Content-Range" in headers:
            self.assertIsNotNone(
                ts_views._parse_content_range_header(headers["Content-Range"]), headers
            )

    @given(total=st.integers(min_value=1, max_value=10**10),
           upstream_content_length=st.none() | st.integers(min_value=1, max_value=10**10))
    def test_plain_streaming_200_advertises_the_representation_length(
        self, total, upstream_content_length,
    ):
        headers = ts_views._build_downstream_length_headers(
            range_header=None, status_code=200, representation_length=total,
            upstream_content_range=None, upstream_content_length=upstream_content_length,
            streaming=True,
        )
        self.assertEqual(headers["Content-Length"], str(total))

    @given(start=st.integers(min_value=0, max_value=10**9),
           span=st.none() | st.integers(min_value=0, max_value=10**9),
           total=st.integers(min_value=1, max_value=10**10))
    def test_synthesised_206_content_range_is_clamped_inside_the_representation(
        self, start, span, total,
    ):
        header = f"bytes={start}-" if span is None else f"bytes={start}-{start + span}"
        headers = ts_views._build_downstream_length_headers(
            range_header=header, status_code=206, representation_length=total,
            upstream_content_range=None, upstream_content_length=None, streaming=True,
        )
        last = total - 1 if span is None else min(start + span, total - 1)
        if start <= last:
            self.assertEqual(headers["Content-Range"], f"bytes {start}-{last}/{total}")
        else:
            self.assertNotIn("Content-Range", headers)


class EofProbeProperties(SimpleTestCase):
    @given(total=st.integers(min_value=1, max_value=WINDOW),
           start=st.integers(min_value=0, max_value=WINDOW))
    # #216: a 1.5 MiB archive classified every seek as an EOF probe.
    @example(total=1_572_864, start=512_000)
    @example(total=1_572_864, start=1_048_576)
    def test_an_archive_no_larger_than_the_window_has_no_tail(self, total, start):
        self.assertFalse(ts_stats.is_near_eof_offset(start, total))
        self.assertFalse(ts_views._is_near_eof_probe(f"bytes={start}-", total))

    @given(total=st.integers(min_value=WINDOW + 1, max_value=10**12), data=st.data())
    def test_a_larger_archive_probes_exactly_in_its_last_window(self, total, data):
        start = data.draw(st.integers(min_value=0, max_value=total + WINDOW))
        expected = start >= total - WINDOW
        self.assertEqual(ts_stats.is_near_eof_offset(start, total), expected)
        self.assertEqual(ts_views._is_near_eof_probe(f"bytes={start}-", total), expected)

    @given(start=offsets)
    def test_unknown_length_probes_only_past_the_fixed_threshold(self, start):
        self.assertEqual(
            ts_views._is_near_eof_probe(f"bytes={start}-", None),
            start >= UNKNOWN_LENGTH_MIN,
        )

    @given(n=st.integers(min_value=1, max_value=10**9),
           total=st.none() | st.integers(min_value=1, max_value=10**12))
    @example(n=500, total=None)  # #141: bytes=-500 parsed as start 0
    def test_a_suffix_range_is_always_a_tail_probe(self, n, total):
        self.assertTrue(ts_views._is_near_eof_probe(f"bytes=-{n}", total))

    @given(header=st.none() | client_range_text,
           total=st.none() | st.integers(min_value=0, max_value=10**12).map(str)
           | st.text(max_size=6))
    @example(header="bytes=-²", total=None)
    def test_eof_probe_classification_never_raises(self, header, total):
        self.assertIsInstance(ts_views._is_near_eof_probe(header, total), bool)


class RangeRewriteProperties(SimpleTestCase):
    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9),
           span=st.none() | st.integers(min_value=-5, max_value=10**9))
    def test_cap_applies_only_to_open_ended_ranges_and_caps_to_exactly_the_span(
        self, start, length, span,
    ):
        header = f"bytes={start}-" if length is None else f"bytes={start}-{start + length}"
        capped = ts_views._cap_open_ended_range(header, span)
        if length is None and span is not None and span > 0:
            self.assertEqual(capped, f"bytes={start}-{start + span - 1}")
        else:
            self.assertEqual(capped, header)

    @given(header=st.none() | client_range_text, span=st.integers(min_value=1, max_value=10**9))
    def test_cap_returns_unparseable_headers_unchanged(self, header, span):
        if ts_views._parse_client_range(header) is None:
            self.assertEqual(ts_views._cap_open_ended_range(header, span), header)

    @given(header=st.none() | client_range_text)
    @example(header="bytes=0-")
    @example(header="")
    def test_full_restart_is_no_header_or_exactly_bytes_zero_open(self, header):
        expected = (not header) or ts_views._parse_client_range(header) == (0, None)
        self.assertEqual(ts_views._is_full_restart_range(header), expected)

    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9),
           base=st.integers(min_value=0, max_value=10**12))
    def test_presentation_mapping_shifts_both_offsets_by_the_base(self, start, length, base):
        header = f"bytes={start}-" if length is None else f"bytes={start}-{start + length}"
        mapped = ts_views._map_client_range_through_presentation(header, base)
        expected_end = None if length is None else base + start + length
        self.assertEqual(ts_views._parse_client_range(mapped), (base + start, expected_end))
        self.assertEqual(ts_views._map_client_range_through_presentation(header, None), header)

    @given(n=st.integers(min_value=1, max_value=10**9), base=st.integers(min_value=0, max_value=10**9))
    @example(n=500, base=50)  # #141: bytes=-500 became bytes=50-550, wider than asked
    def test_suffix_range_passes_through_the_presentation_mapping_unchanged(self, n, base):
        header = f"bytes=-{n}"
        self.assertEqual(ts_views._map_client_range_through_presentation(header, base), header)

    @given(base=st.integers(min_value=0, max_value=10**9),
           length=st.integers(min_value=1, max_value=10**9), data=st.data())
    def test_relative_content_range_inverts_the_mapping_inside_the_presentation(
        self, base, length, data,
    ):
        rel_start = data.draw(st.integers(min_value=0, max_value=length - 1))
        rel_end = data.draw(st.integers(min_value=rel_start, max_value=length - 1))
        upstream = f"bytes {base + rel_start}-{base + rel_end}/{base + length}"
        self.assertEqual(
            ts_views._presentation_relative_content_range(
                upstream, presentation_byte_base=base, presentation_length=length,
            ),
            f"bytes {rel_start}-{rel_end}/{length}",
        )

    @given(value=st.none() | content_range_text,
           base=st.integers(min_value=0, max_value=10**6),
           length=st.integers(min_value=1, max_value=10**6))
    # #141: a range starting before the presentation leaked the absolute CDN range.
    @example(value="bytes 400-499/1000", base=450, length=100)
    @example(value="bytes 100-50/1000", base=0, length=1000)
    def test_relative_content_range_is_none_or_inside_the_presentation(self, value, base, length):
        result = ts_views._presentation_relative_content_range(
            value, presentation_byte_base=base, presentation_length=length,
        )
        if result is None or not value:
            return
        parsed = ts_views._parse_content_range_header(result)
        self.assertIsNotNone(parsed, result)
        self.assertEqual(parsed["total"], length)
        self.assertLess(parsed["end"], length)
