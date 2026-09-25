"""#157: the byte-offset index's channel-id key must equal the value lxml's
own recovery-mode parse produces for the same attribute -- the value
EPGData.tvg_id holds -- under the same own-DOCTYPE decision _open_xmltv_file
makes for that file. Before the fix, _decode_channel_id ran html.unescape
(HTML5-aware, ignorant of any DOCTYPE the file itself declares) while the
database is populated through lxml's recover-mode iterparse under an
HTML-4-only injected DOCTYPE that a file's own DOCTYPE suppresses. The two
disagree for HTML5-only named entities, for HTML 4 entities when the file
carries its own DOCTYPE, for literal whitespace controls and for an entity
reference missing its terminating semicolon.
"""

import os
import tempfile

from django.test import TestCase
from lxml import etree

from apps.epg.models import EPGData, EPGSource
from apps.epg.tasks import (
    _open_xmltv_file,
    build_programme_index,
    find_current_program_for_tvg_id,
)

# (name, channel attribute raw text, file declares its own DOCTYPE)
_DIVERGENT_ROWS = [
    ("html5_only_named_entity", "a&NewLine;b", False),
    ("html4_named_entity_no_own_doctype", "a&eacute;b", False),
    ("html4_named_entity_with_own_doctype", "a&eacute;b", True),
    ("numeric_character_reference", "a&#233;b", False),
    ("literal_tab", "a\tb", False),
    ("entity_missing_semicolon", "a&eacuteb", False),
    # Review round 3, nit 2: every C0 control byte, not just tab/LF/CR, must
    # take the lxml decode path -- the import's own recover-mode parser
    # replaces any of them with U+FFFD, and the fast path's plain
    # errors="replace" decode left them untouched instead.
    ("nul_control_byte", "a\x00b", False),
    ("soh_control_byte", "a\x01b", False),
]


def _write_xmltv(xml):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-8", delete=False
    ) as f:
        f.write(xml)
        return f.name


def _build_xmltv(channel_attr, own_doctype):
    doctype = '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n' if own_doctype else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + doctype
        + "<tv>\n"
        f'  <programme start="20000101000000 +0000" '
        f'stop="20991231235959 +0000" channel="{channel_attr}">\n'
        "    <title>T</title>\n"
        "  </programme>\n"
        "</tv>\n"
    )


def _lxml_channel_attr(file_path):
    """The channel attribute exactly as lxml's own recover-mode iterparse
    reads it for the file's first <programme> element -- the same streaming
    parse the XMLTV import uses elsewhere in this module to populate
    EPGData.tvg_id. This never calls _decode_channel_id, so comparing
    against it is not tautological."""
    with _open_xmltv_file(file_path) as handle:
        parser = etree.iterparse(
            handle,
            events=("end",),
            tag="programme",
            remove_blank_text=True,
            recover=True,
        )
        for _event, elem in parser:
            value = elem.get("channel")
            return (value or "").strip()
    return ""


class ChannelIdIndexLxmlParityTests(TestCase):
    def test_index_key_equals_lxml_value_for_every_divergent_channel_id(self):
        for name, channel_attr, own_doctype in _DIVERGENT_ROWS:
            with self.subTest(name):
                xml = _build_xmltv(channel_attr, own_doctype)
                tmp_path = _write_xmltv(xml)
                try:
                    expected = _lxml_channel_attr(tmp_path)

                    src = EPGSource.objects.create(
                        name=f"Parity {name}",
                        source_type="xmltv",
                        file_path=tmp_path,
                    )
                    build_programme_index(src.id)
                    src.refresh_from_db()
                    channels = src.programme_index["channels"]

                    self.assertEqual(
                        list(channels.keys()),
                        [expected],
                        "the byte-offset index key must equal lxml's own "
                        "value for the same channel attribute, under the "
                        "same DOCTYPE decision _open_xmltv_file made",
                    )
                finally:
                    os.unlink(tmp_path)


class ChannelIdSurrogateCharacterReferenceTests(TestCase):
    def test_build_programme_index_indexes_the_good_channel_past_a_surrogate_reference(self):
        # A character reference to a lone UTF-16 surrogate (valid XML syntax,
        # invalid Unicode text on its own) makes lxml recovery emit the
        # surrogate as unpaired UTF-8 bytes; decoding that back to a Python
        # str for elem.get('c') raises UnicodeDecodeError. One bad channel id
        # must not stop the whole file's index from being built.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="good">\n'
            "    <title>Good</title>\n"
            "  </programme>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="bad&#xD800;id">\n'
            "    <title>Bad</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="Surrogate Reference", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            src.refresh_from_db()

            self.assertIsNotNone(
                src.programme_index,
                "a surrogate character reference in one channel id must not "
                "abort the whole index build",
            )
            self.assertIn(
                "good",
                src.programme_index["channels"],
                "the well-formed channel before the surrogate reference "
                "must still be indexed",
            )
        finally:
            os.unlink(tmp_path)


class ChannelIdEntityLookupTests(TestCase):
    def test_current_programme_found_for_html5_entity_channel_id(self):
        # &NewLine; is an HTML5-only named entity (not in the HTML 4 set
        # this module's injected DOCTYPE declares), so lxml recovery drops
        # it entirely rather than substituting a character: the channel
        # attribute "a&NewLine;b" reads as "ab". A single programme is
        # enough: _parse_programme_element also injects the fixed HTML-4
        # DOCTYPE (now with recover=True), so the same entity that made the
        # decoded index key "ab" also lets the element itself parse.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="a&NewLine;b">\n'
            "    <title>HTML5 Entity Channel</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="HTML5 Entity", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            epg = EPGData.objects.create(
                tvg_id="ab", name="HTML5 Entity Channel", epg_source=src
            )

            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(
                result,
                "the index key must equal lxml's dropped-entity value "
                "'ab' so the lookup finds the programme",
            )
            self.assertEqual(result["title"], "HTML5 Entity Channel")
        finally:
            os.unlink(tmp_path)

    def test_current_programme_found_for_entity_missing_semicolon_channel_id(self):
        # "a&eacuteb" (no terminating ;) is not a well-formed entity
        # reference at all: libxml2's recover mode truncates at the bare
        # '&' rather than substituting a character, so the channel
        # attribute reads as "a", not "aéb". A single programme is enough
        # for the same reason as the HTML5-only case above.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<tv>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="a&eacuteb">\n'
            "    <title>Missing Semicolon Channel</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="Missing Semicolon", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            epg = EPGData.objects.create(
                tvg_id="a", name="Missing Semicolon Channel", epg_source=src
            )

            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(
                result,
                "the index key must equal lxml's truncated-at-'&' value "
                "'a' so the lookup finds the programme",
            )
            self.assertEqual(result["title"], "Missing Semicolon Channel")
        finally:
            os.unlink(tmp_path)

    def test_current_programme_found_when_file_declares_its_own_doctype(self):
        # A file with its own DOCTYPE never gets the HTML-entity DOCTYPE
        # injected (a second DOCTYPE would be invalid XML), so &eacute; is
        # unresolved for both the import and the index: "a&eacute;b" reads
        # as "ab", not "aéb".
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
            "<tv>\n"
            '  <programme start="20000101000000 +0000" '
            'stop="20991231235959 +0000" channel="a&eacute;b">\n'
            "    <title>Own Doctype Channel</title>\n"
            "  </programme>\n"
            "</tv>\n"
        )
        tmp_path = _write_xmltv(xml)
        try:
            src = EPGSource.objects.create(
                name="Own Doctype", source_type="xmltv", file_path=tmp_path
            )
            build_programme_index(src.id)
            epg = EPGData.objects.create(
                tvg_id="ab", name="Own Doctype Channel", epg_source=src
            )

            result = find_current_program_for_tvg_id(epg)

            self.assertIsNotNone(
                result,
                "the index key must equal lxml's unresolved-entity value "
                "'ab' for a file that declares its own DOCTYPE",
            )
            self.assertEqual(result["title"], "Own Doctype Channel")
        finally:
            os.unlink(tmp_path)
