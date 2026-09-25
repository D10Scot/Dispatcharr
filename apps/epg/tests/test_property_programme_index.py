"""Property-based tests for the byte-offset programme index's building blocks.

``build_programme_index`` (apps/epg/tasks.py:2953) and the two current-programme
helpers scan raw XMLTV bytes rather than parsing XML, so every building block
consumes provider-controlled bytes:

* ``_PrependStream`` (:249) - ``_open_xmltv_file`` streams the HTML-entity
  DOCTYPE in front of the file; lxml may ``read()`` with any size.
* ``_open_xmltv_file`` (:290) - injects that DOCTYPE once, after an XML
  declaration if present, and never into a file that declares its own.
* ``_find_programme_tag`` (:2910) - the scanner. Finds the first
  ``<programme`` followed by whitespace, ``>`` or ``/``.
* ``_CHANNEL_ATTR_RE`` (:2894) - the ``channel=`` extractor.
* ``_decode_channel_id`` is covered by test_property_channel_id_parity.py,
  which needs C-2's new signature.

Closes the programme-index part of #202 (and duplicates #274, #158, #74).
"""

import io
import os
import re
import string
import tempfile
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg import tasks as epg_tasks
from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _HTML_ENTITY_DOCTYPE,
    _MAX_START_TAG,
    _PROGRAMME_TAG,
    _PrependStream,
    _find_programme_tag,
    _open_xmltv_file,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class _QuietTaskWarnings(SimpleTestCase):
    """Silence apps.epg.tasks' per-call WARNING so 200 draws do not flood the CI log."""

    def setUp(self):
        patcher = mock.patch.object(epg_tasks.logger, "warning")
        patcher.start()
        self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# _PrependStream
# ---------------------------------------------------------------------------

class PrependStreamProperties(SimpleTestCase):
    @given(
        prefix=st.binary(max_size=64),
        body=st.binary(max_size=256),
        sizes=st.lists(st.integers(0, 80), max_size=30),
    )
    def test_any_sequence_of_sized_reads_reassembles_prefix_then_body(
        self, prefix, body, sizes
    ):
        stream = _PrependStream(prefix, io.BytesIO(body))
        out = bytearray()
        for size in sizes:
            chunk = stream.read(size)
            self.assertLessEqual(len(chunk), size)  # read(n) never over-returns
            out += chunk
        out += stream.read()  # drain
        self.assertEqual(bytes(out), prefix + body)
        self.assertEqual(stream.read(), b"")  # exhausted is empty, not an error
        self.assertEqual(stream.read(7), b"")


# ---------------------------------------------------------------------------
# _open_xmltv_file
# ---------------------------------------------------------------------------

_XML_DECL = b'<?xml version="1.0" encoding="UTF-8"?>'
# Readable text; '&' and '<' are only ever emitted as the entity refs below.
_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + " .,-", max_size=40
)


def _write_tmp(test, data):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    test.addCleanup(os.unlink, path)
    return path


def _read_all(stream):
    try:
        return stream.read()
    finally:
        stream.close()


class OpenXmltvFileProperties(SimpleTestCase):
    @given(with_decl=st.booleans(), title=_TEXT, padding=st.integers(0, 600))
    def test_the_doctype_is_injected_once_and_the_file_bytes_survive(
        self, with_decl, title, padding
    ):
        body = (
            b"<tv>" + b" " * padding
            + b"<programme><title>" + title.encode() + b"&eacute;</title>"
            + b"</programme></tv>"
        )
        original = (_XML_DECL + b"\n" if with_decl else b"") + body
        out = _read_all(_open_xmltv_file(_write_tmp(self, original)))
        self.assertEqual(out.count(_HTML_ENTITY_DOCTYPE), 1)
        if with_decl:
            # Injected right after the declaration, which stays first.
            self.assertTrue(out.startswith(_XML_DECL + b"\n" + _HTML_ENTITY_DOCTYPE))
            self.assertEqual(
                out.replace(b"\n" + _HTML_ENTITY_DOCTYPE, b"", 1), original
            )
        else:
            self.assertEqual(out, _HTML_ENTITY_DOCTYPE + original)
        # The point of the injection: lxml resolves an HTML 4 entity.
        root = etree.fromstring(out)
        self.assertEqual(root.findtext("programme/title"), title + "é")

    @given(
        doctype=st.sampled_from(
            [b"<!DOCTYPE tv SYSTEM \"xmltv.dtd\">", b"<!doctype tv>", b"<!DocType tv>"]
        ),
        title=_TEXT,
    )
    def test_a_file_that_declares_its_own_doctype_is_returned_unchanged(
        self, doctype, title
    ):
        original = (
            _XML_DECL + b"\n" + doctype + b"\n<tv><programme><title>"
            + title.encode() + b"</title></programme></tv>"
        )
        out = _read_all(_open_xmltv_file(_write_tmp(self, original)))
        self.assertEqual(out, original)


# ---------------------------------------------------------------------------
# _find_programme_tag
# ---------------------------------------------------------------------------

# Byte soup biased towards the needle and its false-match neighbours.
_FRAGMENTS = st.sampled_from(
    [b"<programme", b"<programme ", b"<programme>", b"<programme/",
     b"<programmeX", b"<programmes", b"<program", b">", b" ", b"\t",
     b'channel="a"', b"x", b"<", b"</programme>"]
)
tag_soup = st.one_of(
    st.binary(max_size=200),
    st.lists(_FRAGMENTS, max_size=25).map(b"".join),
)
_FIRST_CANDIDATE = re.compile(rb"<programme(?:[ \t\n\r>/]|\Z)")


class FindProgrammeTagProperties(_QuietTaskWarnings):
    @given(buf=tag_soup, start=st.integers(0, 220))
    def test_finds_the_first_real_start_tag_and_its_closing_bracket(
        self, buf, start
    ):
        # Buffers stay far below _MAX_START_TAG, so the oversize arm cannot
        # fire here; it has its own test below.
        pos, end = _find_programme_tag(buf, start)
        # Oracle: a regex for "<programme" followed by a tag-follow byte, or
        # at the very end of the buffer (the "need more data" case).
        m = _FIRST_CANDIDATE.search(buf, start)
        if m is None:
            self.assertEqual((pos, end), (-1, -1))
            return
        self.assertEqual(pos, m.start())
        close = buf.find(b">", pos + len(_PROGRAMME_TAG))
        self.assertEqual(end, close)  # -1 means "need more data"

    @given(prefix=st.binary(max_size=40).filter(lambda b: _PROGRAMME_TAG not in b))
    def test_a_false_match_is_skipped_and_the_next_real_tag_found(self, prefix):
        buf = prefix + b"<programmeXYZ a='1'> <programme channel='b'>"
        pos, end = _find_programme_tag(buf, 0)
        self.assertEqual(pos, buf.rfind(b"<programme "))
        self.assertEqual(end, len(buf) - 1)

    @given(extra=st.integers(0, 64))
    def test_a_start_tag_longer_than_the_bound_is_rejected_not_waited_on(
        self, extra
    ):
        buf = b"<programme " + b"a" * (_MAX_START_TAG + extra)
        self.assertEqual(_find_programme_tag(buf, 0), (-1, -1))

    @given(short=st.integers(0, _MAX_START_TAG - len(b"<programme ") - 1))
    def test_an_unterminated_tag_within_the_bound_asks_for_more_data(self, short):
        buf = b"<programme " + b"a" * short
        self.assertEqual(_find_programme_tag(buf, 0), (0, -1))


# ---------------------------------------------------------------------------
# _CHANNEL_ATTR_RE
# ---------------------------------------------------------------------------

class ChannelAttrRegexProperties(SimpleTestCase):
    @given(buf=st.binary(max_size=200) | tag_soup)
    def test_exactly_one_quote_style_captures_and_never_contains_its_quote(
        self, buf
    ):
        for m in _CHANNEL_ATTR_RE.finditer(buf):
            dq, sq = m.group(1), m.group(2)
            self.assertEqual((dq is not None) + (sq is not None), 1)
            if dq is not None:
                self.assertTrue(dq)
                self.assertNotIn(b'"', dq)
            else:
                self.assertTrue(sq)
                self.assertNotIn(b"'", sq)

    @given(
        value=st.text(
            alphabet=string.ascii_letters + string.digits + " \t-_.:/&;#'",
            min_size=1, max_size=40,
        ),
        spaces=st.sampled_from(["", " ", "  ", "\t"]),
    )
    def test_a_double_quoted_value_round_trips_verbatim(self, value, spaces):
        buf = f'<programme start="x" channel{spaces}={spaces}"{value}">'.encode()
        m = _CHANNEL_ATTR_RE.search(buf)
        self.assertEqual(m.group(1), value.encode())

    def test_an_empty_channel_attribute_never_matches(self):
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b'<programme channel="">'))
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b"<programme channel=''>"))
