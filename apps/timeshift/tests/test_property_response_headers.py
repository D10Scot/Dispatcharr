"""Property-based tests for timeshift downstream response-header helpers.

``_build_downstream_length_headers`` and ``_extract_representation_length``
in ``apps/timeshift/views.py`` translate upstream (provider/CDN) headers into
the ``Content-Length`` / ``Content-Range`` the IPTV client sees. Invariants
read from the implementation:

- Every returned header dict carries ``Accept-Ranges: bytes``.
- A synthesized ``Content-Length`` is always the decimal string of a
  non-negative integer (the known inverted-upstream-Content-Range defect is
  deliberately not asserted here — it is filed as a separate finding).
- For a plain streaming 200 GET with a known representation length, the
  response always advertises that length (clients use it for archive
  duration).
- ``_extract_representation_length`` prefers the ``Content-Range`` total over
  ``Content-Length`` and never raises on missing/garbage headers.

No Redis or DB. Derandomized ``dispatcharr-ci`` profile, matching the existing
``test_property_*.py`` suites.
"""

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift import views

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_nonneg = st.integers(min_value=0, max_value=10**12)
_maybe_len = st.one_of(st.none(), _nonneg)


def _resp(headers):
    class _R:
        def __init__(self, h):
            self.headers = h

    return _R(headers)


class BuildDownstreamLengthHeaderProperties(SimpleTestCase):
    @given(
        range_header=st.one_of(st.none(), st.just("bytes=0-")),
        status_code=st.sampled_from([200, 206]),
        representation_length=_maybe_len,
        upstream_content_range=st.one_of(st.none(), st.just("bytes 0-9/100")),
        upstream_content_length=st.one_of(st.none(), _nonneg),
        streaming=st.booleans(),
    )
    def test_always_carries_accept_ranges(
        self,
        range_header,
        status_code,
        representation_length,
        upstream_content_range,
        upstream_content_length,
        streaming,
    ):
        headers = views._build_downstream_length_headers(
            range_header=range_header,
            status_code=status_code,
            representation_length=representation_length,
            upstream_content_range=upstream_content_range,
            upstream_content_length=upstream_content_length,
            streaming=streaming,
        )
        self.assertEqual(headers.get("Accept-Ranges"), "bytes")

    @given(
        representation_length=st.integers(min_value=1, max_value=10**12),
    )
    def test_plain_streaming_200_advertises_representation_length(
        self, representation_length
    ):
        headers = views._build_downstream_length_headers(
            range_header=None,
            status_code=200,
            representation_length=representation_length,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=True,
        )
        self.assertEqual(
            headers.get("Content-Length"), str(representation_length)
        )

    @given(
        range_header=st.just("bytes=0-"),
        representation_length=st.integers(min_value=1, max_value=10**12),
    )
    def test_206_synthesizes_content_range_within_bounds(
        self, range_header, representation_length
    ):
        headers = views._build_downstream_length_headers(
            range_header=range_header,
            status_code=206,
            representation_length=representation_length,
            upstream_content_range=None,
            upstream_content_length=None,
            streaming=True,
        )
        cr = headers.get("Content-Range")
        self.assertIsNotNone(cr)
        # bytes START-END/TOTAL with END clamped to TOTAL-1.
        body, total = cr[6:].rsplit("/", 1)
        start_s, end_s = body.split("-", 1)
        self.assertEqual(int(total), representation_length)
        self.assertEqual(int(start_s), 0)
        self.assertEqual(int(end_s), representation_length - 1)


class ExtractRepresentationLengthProperties(SimpleTestCase):
    @given(total=st.integers(min_value=1, max_value=10**12))
    def test_content_range_total_wins(self, total):
        r = _resp(
            {"Content-Range": f"bytes 0-9/{total}", "Content-Length": "5"}
        )
        self.assertEqual(views._extract_representation_length(r), total)

    @given(length=st.integers(min_value=0, max_value=10**12))
    def test_content_length_fallback(self, length):
        r = _resp({"Content-Length": str(length)})
        self.assertEqual(views._extract_representation_length(r), length)

    def test_none_response_is_none(self):
        self.assertIsNone(views._extract_representation_length(None))

    def test_missing_headers_is_none(self):
        self.assertIsNone(views._extract_representation_length(_resp({})))

    @given(garbage=st.text(max_size=40))
    def test_garbage_content_length_is_none(self, garbage):
        try:
            int(garbage)
            return  # only non-integer strings are interesting here
        except (TypeError, ValueError):
            pass
        r = _resp({"Content-Length": garbage})
        self.assertIsNone(views._extract_representation_length(r))

    @given(total=st.integers(min_value=1, max_value=10**12))
    def test_star_total_falls_back_to_content_length(self, total):
        r = _resp(
            {"Content-Range": "bytes 0-9/*", "Content-Length": str(total)}
        )
        self.assertEqual(views._extract_representation_length(r), total)
