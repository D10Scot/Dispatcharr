"""Property: the programme index's channel key equals the value lxml stores (#157).

``build_programme_index`` (apps/epg/tasks.py:2953) keys its byte-offset index
with ``_CHANNEL_ATTR_RE`` (:2894) plus ``_decode_channel_id`` (:2902), while
``parse_programs_for_source`` stores lxml's recover-mode value
(:2204-2214) behind ``_open_xmltv_file`` (:290). ``find_current_program_for_tvg_id``
joins the two, so any disagreement makes that channel's current programme
invisible. At seed they disagree for HTML5-only entities, for HTML 4 entities in
a file carrying its own DOCTYPE, for literal tabs/newlines and for
semicolon-less entities. C-2 (#157) changes the signature to
``_decode_channel_id(raw, quote=b'"', entity_doctype=True)`` and adds
``_xmltv_file_gets_entity_doctype(file_path)``; this module is written against
that and therefore lands after C-2.

The oracle is lxml's own parse of a real file through ``_open_xmltv_file``,
which the byte-level path never calls, so the property is not tautological.

Closes the _decode_channel_id cross-validation part of #202 (and duplicates
#274, #158, #74).
"""

import os
import tempfile

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _decode_channel_id,
    _open_xmltv_file,
    _xmltv_file_gets_entity_doctype,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_XML_DECL = b'<?xml version="1.0" encoding="UTF-8"?>'


def _write_tmp(test, data):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    test.addCleanup(os.unlink, path)
    return path


# Byte soup for the no-raise property (same shape as the index scanner's).
_FRAGMENTS = st.sampled_from(
    [b"<programme ", b'channel="', b"channel='", b'"', b"'", b"&", b";",
     b"&amp;", b"&eacute", b"&#", b"x", b" ", b"\t", b"\xff", b"\xc3"]
)
tag_soup = st.lists(_FRAGMENTS, max_size=25).map(b"".join)

# Pieces of a provider channel id: plain text, whitespace escapes lxml
# normalises, HTML 4 and HTML5-only named entities, numeric refs, and
# malformed refs (no semicolon, unknown name, bare ampersand).
_ID_PIECES = st.sampled_from(
    ["a", "B", "7", ".", "-", "_", " ", "\t", "\n", "\r", "é", "日",
     "&amp;", "&lt;", "&gt;", "&apos;", "&quot;", "&eacute;", "&nbsp;",
     "&Uuml;", "&NewLine;", "&Tab;", "&#233;", "&#x41;", "&#9;", "&eacute",
     "&bogus;", "&"]
)
channel_ids = st.lists(_ID_PIECES, min_size=1, max_size=8).map("".join)

_OWN_DOCTYPE = b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'


def _lxml_programme_channel(path):
    """Oracle: the channel value the bulk parser stores, through the same
    _open_xmltv_file + recover-mode iterparse (tasks.py:2204-2214), stripped
    as EPGData.tvg_id is. None if lxml recovered no <programme>."""
    source = _open_xmltv_file(path)
    try:
        for _, elem in etree.iterparse(
            source, events=("end",), tag="programme",
            remove_blank_text=True, recover=True,
        ):
            value = elem.get("channel")
            return None if value is None else value.strip()
    finally:
        source.close()
    return None


class DecodeChannelIdMatchesLxmlProperties(SimpleTestCase):
    # C-2's #157 table, every divergent row plus the two the existing tests pin.
    @example(raw="a&NewLine;b", quote='"', own_doctype=False)  # #157 HTML5-only name
    @example(raw="a&eacute;b", quote='"', own_doctype=True)  # #157 own DOCTYPE
    @example(raw="a\tb", quote='"', own_doctype=False)  # #157 literal tab
    @example(raw="a&eacuteb", quote='"', own_doctype=False)  # #157 no semicolon
    @example(raw="a&eacute;b", quote='"', own_doctype=False)  # #157 control
    @example(raw="a&#233;b", quote='"', own_doctype=False)  # #157 control
    @example(raw=" A&amp;E.us ", quote='"', own_doctype=False)  # test_programme_index.py:170
    @example(raw="it&apos;s", quote="'", own_doctype=False)  # test_programme_index.py:406
    @given(
        raw=channel_ids,
        quote=st.sampled_from(['"', "'"]),
        own_doctype=st.booleans(),
    )
    def test_the_index_key_equals_the_value_lxml_stores(
        self, raw, quote, own_doctype
    ):
        raw = raw.replace(quote, "")
        if not raw:
            raw = "a"
        doc = (
            _XML_DECL + b"\n" + (_OWN_DOCTYPE if own_doctype else b"")
            + b"<tv><programme start=\"20260101000000 +0000\" channel="
            + quote.encode() + raw.encode() + quote.encode()
            + b"><title>t</title></programme></tv>"
        )
        path = _write_tmp(self, doc)
        stored = _lxml_programme_channel(path)
        if stored is None:
            return  # lxml dropped the programme: no row, nothing to join
        # The byte-level path, exactly as build_programme_index takes it.
        m = _CHANNEL_ATTR_RE.search(doc)
        group_quote = b'"' if m.group(1) is not None else b"'"
        key = _decode_channel_id(
            m.group(1) or m.group(2), group_quote,
            _xmltv_file_gets_entity_doctype(path),
        )
        self.assertEqual(key, stored)

    @given(buf=st.binary(max_size=200) | tag_soup, entity_doctype=st.booleans())
    def test_every_captured_id_decodes_to_a_stripped_string_without_raising(
        self, buf, entity_doctype
    ):
        for m in _CHANNEL_ATTR_RE.finditer(buf):
            quote = b'"' if m.group(1) is not None else b"'"
            key = _decode_channel_id(m.group(1) or m.group(2), quote, entity_doctype)
            self.assertIsInstance(key, str)
            self.assertEqual(key, key.strip())
