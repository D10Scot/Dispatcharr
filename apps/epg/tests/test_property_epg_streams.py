"""Property-based tests for the EPG programme-index byte-scanning helpers.

The byte-offset index (``build_programme_index`` and its lookup helpers) scans
raw XMLTV bytes instead of parsing XML, so its building blocks must be robust
to provider-controlled byte sequences:

* ``_PrependStream`` — the read()-contract of the DOCTYPE-injecting wrapper
  used by ``_open_xmltv_file``: concatenating any sequence of sized reads must
  reproduce ``prefix + file`` exactly.
* ``_find_programme_tag`` — the raw scanner. Must never raise, must return
  ``(-1, -1)`` when no complete start tag exists, and must pair every found
  tag with the offset of its closing ``>``.

Runs without the database or Redis (SimpleTestCase, pure functions).
"""

import io
import string

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.epg.tasks import (
    _MAX_START_TAG,
    _PROGRAMME_TAG,
    _PrependStream,
    _find_programme_tag,
)

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# _PrependStream
# ---------------------------------------------------------------------------

class PrependStreamProperties(SimpleTestCase):
    @given(
        prefix=st.binary(max_size=64),
        body=st.binary(max_size=256),
        sizes=st.lists(st.integers(1, 40), max_size=30),
    )
    def test_chunked_reads_reassemble_exactly(self, prefix, body, sizes):
        stream = _PrependStream(prefix, io.BytesIO(body))
        out = bytearray()
        for size in sizes:
            out += stream.read(size)
        out += stream.read()  # drain the remainder
        self.assertEqual(bytes(out), prefix + body)

    @given(prefix=st.binary(max_size=64), body=st.binary(max_size=256))
    def test_single_full_read(self, prefix, body):
        stream = _PrependStream(prefix, io.BytesIO(body))
        self.assertEqual(stream.read(-1), prefix + body)
        # A second read after exhaustion must be empty, not an error.
        self.assertEqual(stream.read(-1), b"")

    @given(
        prefix=st.binary(min_size=1, max_size=64),
        body=st.binary(max_size=256),
        size=st.integers(1, 64),
    )
    def test_read_size_is_never_exceeded(self, prefix, body, size):
        stream = _PrependStream(prefix, io.BytesIO(body))
        while True:
            chunk = stream.read(size)
            if not chunk:
                break
            self.assertLessEqual(len(chunk), size)


# ---------------------------------------------------------------------------
# _find_programme_tag
# ---------------------------------------------------------------------------

# Byte soup biased towards fragments of the needle.
tag_soup = st.binary(max_size=300) | st.text(
    alphabet=string.ascii_letters + string.digits + "<>/= '\"",
    max_size=300,
).map(lambda s: s.encode())


class FindProgrammeTagProperties(SimpleTestCase):
    @given(buf=tag_soup, start=st.integers(0, 300))
    def test_never_raises_and_result_is_coherent(self, buf, start):
        pos, end = _find_programme_tag(buf, start)
        if pos == -1:
            self.assertEqual(end, -1)
            return
        # Found a candidate: it must point at the needle within bounds.
        self.assertGreaterEqual(pos, start)
        self.assertTrue(buf[pos : pos + len(_PROGRAMME_TAG)] == _PROGRAMME_TAG)
        if end != -1:
            # end points at the closing '>' of the start tag.
            self.assertEqual(buf[end : end + 1], b">")
            self.assertGreater(end, pos)
            self.assertLess(end, pos + _MAX_START_TAG)

    @given(
        prefix=st.binary(max_size=40),
        attrs=st.text(
            alphabet=string.ascii_letters + string.digits + " =\"'",
            max_size=40,
        ).map(lambda s: s.replace(">", "").encode()),
    )
    def test_finds_wellformed_tag(self, prefix, attrs):
        assume(_PROGRAMME_TAG not in prefix)
        buf = prefix + b"<programme " + attrs + b">rest"
        pos, end = _find_programme_tag(buf, 0)
        self.assertEqual(pos, len(prefix))
        self.assertEqual(buf[end : end + 1], b">")

    @given(junk=st.binary(max_size=80))
    def test_no_needle_no_match(self, junk):
        assume(_PROGRAMME_TAG not in junk)
        pos, end = _find_programme_tag(junk, 0)
        self.assertEqual((pos, end), (-1, -1))

    def test_truncated_tag_reports_need_more_data(self):
        # '<programme' at the very end of the buffer: candidate but unterminated.
        self.assertEqual(_find_programme_tag(b"xx <programme", 0), (3, -1))

    def test_false_positive_is_skipped(self):
        # '<programmeXYZ' must not match; a later real tag is found instead.
        buf = b"<programmeXYZ <programme>"
        pos, end = _find_programme_tag(buf, 0)
        self.assertEqual(pos, buf.find(b"<programme>"))
