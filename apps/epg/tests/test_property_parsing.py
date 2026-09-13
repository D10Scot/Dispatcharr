"""Property-based tests for EPG parsing surfaces.

apps/epg/tasks.py and friends consume untrusted provider XMLTV files — the
timestamps, channel ids and description text all come from a remote EPG source
— so the core contract of these helpers is robustness and predictability:

* ``parse_xmltv_time`` either returns an aware datetime (normalized to UTC)
  or raises ``ValueError``; it never raises any other exception type and never
  returns None. A timestamp with a ``+hhmm``/``-hhmm`` suffix denotes local
  time at that offset, so parsing must round-trip through UTC.
* ``_find_programme_tag`` scans raw bytes for ``<programme`` start tags,
  rejecting false matches like ``<programmeXYZ`` and bounding the start-tag
  scan; it never raises and never reports out-of-range offsets.
* ``_decode_channel_id`` mirrors how ``EPGData.tvg_id`` is stored: UTF-8 with
  replacement, HTML entities resolved, stripped — so byte-level index keys
  equal the lxml-parsed channel ids.
* ``extract_season_episode_from_description`` only recognises S/E patterns at
  the *start* of the text and returns the cleaned remainder; a non-match
  returns the input unchanged.
* ``detect_file_format`` trusts magic bytes over the file extension.
* ``parse_text_query`` builds a Q object for arbitrary user input without
  raising, and double-quoted phrases stay atomic (never split on operators).
* ``sd_credential_fingerprint`` is deterministic and treats ``None`` like the
  empty string, matching its lockout/token-cache matching contract.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

import html
import io
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from lxml import etree

from django.db.models import Q
from django.test import SimpleTestCase
from django.utils import timezone
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.epg.query_utils import parse_text_query
from apps.epg.sd_utils import sd_credential_fingerprint
from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _MAX_START_TAG,
    _PrependStream,
    _decode_channel_id,
    _find_programme_tag,
    detect_file_format,
    parse_xmltv_time,
)
from apps.epg.utils import (
    extract_season_episode,
    extract_season_episode_from_description,
)

# CI-deterministic profile — see live_proxy test_property_log_parsers.py.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def _no_trace_logger():
    """A logger without the TRACE monkey-patch, so tests can silence parse_xmltv_time.

    The project logger emits two f-string trace calls per successful parse;
    over thousands of Hypothesis examples that formatting dominates runtime.
    """
    return logging.getLogger("epg_property_test_silent")


# ---------------------------------------------------------------------------
# parse_xmltv_time
# ---------------------------------------------------------------------------

xmltv_datetimes = st.datetimes(
    min_value=datetime(1900, 1, 1),
    max_value=datetime(9999, 12, 31),
    timezones=st.none(),
)


def _format_naive(dt):
    # strftime drops microseconds; XMLTV timestamps are second-precision.
    return dt.replace(microsecond=0).strftime("%Y%m%d%H%M%S")


class XmltvTimeProperties(SimpleTestCase):
    def setUp(self):
        patcher = patch("apps.epg.tasks.logger", _no_trace_logger())
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(dt=xmltv_datetimes)
    def test_no_timezone_round_trips_as_utc(self, dt):
        """A bare 14-digit timestamp is interpreted as UTC and round-trips."""
        parsed = parse_xmltv_time(_format_naive(dt))
        self.assertEqual(parsed.tzinfo, dt_timezone.utc)
        self.assertEqual(parsed.replace(tzinfo=None), dt.replace(microsecond=0))

    @given(
        dt=xmltv_datetimes,
        sign=st.sampled_from(["+", "-"]),
        hours=st.integers(min_value=0, max_value=23),
        minutes=st.integers(min_value=0, max_value=59),
    )
    def test_timezone_suffix_normalizes_to_utc(self, dt, sign, hours, minutes):
        """``<stamp> ±hhmm`` means local time at that offset; result is UTC."""
        offset = timedelta(hours=hours, minutes=minutes)
        if sign == "-":
            offset = -offset
        s = f"{_format_naive(dt)} {sign}{hours:02d}{minutes:02d}"
        parsed = parse_xmltv_time(s)
        self.assertEqual(parsed.tzinfo, dt_timezone.utc)
        naive = dt.replace(microsecond=0)
        expected = naive.replace(tzinfo=dt_timezone(offset)).astimezone(dt_timezone.utc)
        self.assertEqual(parsed, expected)

    @given(s=st.text(max_size=40))
    def test_arbitrary_input_raises_only_value_error_or_succeeds(self, s):
        """Untrusted timestamps raise ValueError (documented) — never any
        other exception type — or parse to an aware UTC datetime."""
        try:
            parsed = parse_xmltv_time(s)
        except ValueError:
            return
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))


# ---------------------------------------------------------------------------
# _find_programme_tag
# ---------------------------------------------------------------------------

# Buffer text deliberately excludes '<' so every '<programme' occurrence is one
# the test injected explicitly.
buf_text = st.text(
    alphabet=st.characters(blacklist_characters="<"), max_size=200
).map(lambda s: s.encode("utf-8", errors="replace"))


class FindProgrammeTagProperties(SimpleTestCase):
    @given(buf=st.binary(max_size=300))
    def test_never_raises_and_stays_in_bounds(self, buf):
        """Arbitrary bytes: returns (-1, -1) or a valid in-buffer span."""
        tag_pos, tag_end = _find_programme_tag(buf, 0)
        if tag_pos == -1:
            self.assertEqual(tag_end, -1)
            return
        self.assertTrue(0 <= tag_pos < len(buf))
        self.assertEqual(buf[tag_pos : tag_pos + 10], b"<programme")
        if tag_end != -1:
            self.assertTrue(tag_pos < tag_end < len(buf))
            self.assertEqual(buf[tag_end : tag_end + 1], b">")

    @given(prefix=buf_text, suffix=buf_text)
    def test_finds_injected_tag_at_exact_position(self, prefix, suffix):
        """A well-formed tag is found exactly where it was injected."""
        tag = b'<programme start="20240101000000" channel="abc">'
        buf = prefix + tag + suffix
        tag_pos, tag_end = _find_programme_tag(buf, 0)
        self.assertEqual(tag_pos, len(prefix))
        self.assertEqual(tag_end, len(prefix) + len(tag) - 1)

    @given(prefix=buf_text, middle=buf_text, suffix=buf_text)
    def test_false_match_is_skipped(self, prefix, middle, suffix):
        """``<programmeXYZ`` is not a programme tag and must be skipped."""
        real_tag = b'<programme channel="abc">'
        buf = prefix + b"<programmeXYZ" + middle + real_tag + suffix
        tag_pos, tag_end = _find_programme_tag(buf, 0)
        expected = len(prefix) + len(b"<programmeXYZ") + len(middle)
        self.assertEqual(tag_pos, expected)
        self.assertEqual(tag_end, expected + len(real_tag) - 1)

    def test_oversized_start_tag_is_rejected(self):
        """A start tag longer than _MAX_START_TAG yields (-1, -1), not a hang
        or a spurious match inside the attribute soup."""
        buf = b"<programme " + b"A" * (_MAX_START_TAG + 100)
        tag_pos, tag_end = _find_programme_tag(buf, 0)
        self.assertEqual((tag_pos, tag_end), (-1, -1))


# ---------------------------------------------------------------------------
# _decode_channel_id
# ---------------------------------------------------------------------------


class DecodeChannelIdProperties(SimpleTestCase):
    @given(raw=st.binary(max_size=200))
    def test_never_raises_on_arbitrary_bytes(self, raw):
        """Invalid UTF-8 is replaced, never raised (errors='replace')."""
        result = _decode_channel_id(raw)
        self.assertIsInstance(result, str)

    @given(s=st.text(max_size=100))
    def test_unescaped_text_round_trips_modulo_strip(self, s):
        """Text without '&' passes through unchanged apart from stripping."""
        assume("&" not in s)
        self.assertEqual(_decode_channel_id(s.encode("utf-8")), s.strip())

    @given(s=st.text(max_size=100))
    def test_html_escaped_form_decodes_back(self, s):
        """``&amp;``-style entities resolve, matching lxml-parsed tvg_ids."""
        assume("&" not in s)  # avoid double-unescaping ambiguity on round trip
        escaped = html.escape(s.strip(), quote=True)
        self.assertEqual(_decode_channel_id(escaped.encode("utf-8")), s.strip())

    @given(
        s=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")), max_size=50
        ),
        lead=st.text(alphabet=" \t\n\r", max_size=5),
        trail=st.text(alphabet=" \t\n\r", max_size=5),
    )
    def test_surrounding_whitespace_is_stripped(self, s, lead, trail):
        assume(s.strip())
        self.assertEqual(
            _decode_channel_id((lead + s + trail).encode("utf-8")), s.strip()
        )


# ---------------------------------------------------------------------------
# Season/episode extraction
# ---------------------------------------------------------------------------

clean_text = st.text(
    alphabet=st.characters(blacklist_categories=("C",)), max_size=120
)


class SeasonEpisodeProperties(SimpleTestCase):
    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=0, max_value=9999),
        rest=clean_text,
    )
    def test_sxxeyy_prefix_is_recognised(self, season, episode, rest):
        desc = f"S{season}E{episode} {rest}"
        s, e, cleaned = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))
        self.assertEqual(cleaned, rest.strip())

    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=0, max_value=9999),
        rest=clean_text,
    )
    def test_long_form_prefix_is_recognised(self, season, episode, rest):
        # The recognised prefix spans 'Season <s> Episode <e>' plus one trailing
        # separator class char ([\s\-:.]); the remainder is what survives.
        desc = f"Season {season} Episode {episode} {rest}"
        s, e, cleaned = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))
        self.assertEqual(cleaned, rest.lstrip(" \t-:.").strip())

    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=10, max_value=9999),
        rest=clean_text,
    )
    def test_nxnn_prefix_is_recognised(self, season, episode, rest):
        """The 1x01 form requires a 2+ digit episode to avoid false positives."""
        desc = f"{season}x{episode:02d} {rest}"
        s, e, cleaned = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))
        self.assertEqual(cleaned, rest.lstrip(" \t-:.").strip())

    @given(desc=clean_text)
    def test_no_match_returns_input_unchanged(self, desc):
        """When no prefix pattern matches, the description is returned as-is."""
        assume(not re.match(r"^[\s\-:]*S\d+\s*E\d+", desc, re.IGNORECASE))
        assume(not re.match(r"^[\s\-:]*Season\s*\d+\s*Episode\s*\d+", desc, re.IGNORECASE))
        assume(not re.match(r"^[\s\-:]*\d+x\d{2}", desc))
        s, e, cleaned = extract_season_episode_from_description(desc)
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertIs(cleaned, desc)

    @given(desc=st.one_of(st.none(), st.text(max_size=120)))
    def test_extract_season_episode_prefers_explicit_fields(self, desc):
        """Explicit season/episode in custom_properties win over fallbacks."""
        cp = {"season": 7, "episode": 3, "onscreen_episode": "S1 E2"}
        s, e = extract_season_episode(cp, description=desc)
        self.assertEqual((s, e), (7, 3))

    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=0, max_value=9999),
    )
    def test_onscreen_episode_fills_missing_halves(self, season, episode):
        """onscreen_episode supplies only the halves custom_properties lacks."""
        s, e = extract_season_episode(
            {"onscreen_episode": f"S{season} E{episode}"}, description=None
        )
        self.assertEqual((s, e), (season, episode))
        # season present, episode missing -> only episode comes from onscreen
        s, e = extract_season_episode(
            {"season": 42, "onscreen_episode": f"S{season} E{episode}"},
            description=None,
        )
        self.assertEqual((s, e), (42, episode))


# ---------------------------------------------------------------------------
# Cross-validation: byte-level channel scan vs lxml
# ---------------------------------------------------------------------------

# build_programme_index / _read_programs_at_offsets key the byte-level index by
# _CHANNEL_ATTR_RE + _decode_channel_id; parse_programs_for_source keys the DB
# by lxml's parsed attribute value. For the index to resolve channels to their
# programmes, the two must agree on every channel id the file contains.
# Attribute values must also be legal XML: no control/format/surrogate chars.
xml_safe_text = st.text(
    alphabet=st.characters(
        blacklist_characters='<>&"\'', blacklist_categories=("Cc", "Cf", "Cs", "Co")
    ),
    max_size=60,
)


class ChannelIdCrossValidationProperties(SimpleTestCase):
    @given(
        channel=xml_safe_text,
        lead_ws=st.text(alphabet=" \t", max_size=3),
        trail_ws=st.text(alphabet=" \t", max_size=3),
        quote=st.sampled_from(['"', "'"]),
    )
    def test_byte_scan_matches_lxml_parse(self, channel, lead_ws, trail_ws, quote):
        """For entity-free ids, the regex+decode scan agrees with lxml exactly,
        including quote style and attribute-interior whitespace."""
        assume(channel.strip())  # _CHANNEL_ATTR_RE requires a non-empty id
        ch_id = lead_ws + channel.strip() + trail_ws
        elem = f'<programme channel={quote}{ch_id}{quote} start="20240101000000"/>'.encode()
        m = _CHANNEL_ATTR_RE.search(elem)
        self.assertIsNotNone(m)
        scanned = _decode_channel_id(m.group(1) or m.group(2))
        parsed = etree.fromstring(elem).get("channel").strip()
        self.assertEqual(scanned, parsed)

    @given(channel=xml_safe_text)
    def test_entity_encoded_attribute_matches_lxml(self, channel):
        """An id stored with XML entities in the raw bytes decodes to lxml's
        resolved value — the reason _decode_channel_id exists."""
        assume(channel.strip())
        raw_id = html.escape(channel.strip(), quote=True)
        elem = f'<programme channel="{raw_id}" start="20240101000000"/>'.encode()
        m = _CHANNEL_ATTR_RE.search(elem)
        self.assertIsNotNone(m)
        scanned = _decode_channel_id(m.group(1) or m.group(2))
        parsed = etree.fromstring(elem).get("channel").strip()
        self.assertEqual(scanned, parsed)


# ---------------------------------------------------------------------------
# _PrependStream read contract
# ---------------------------------------------------------------------------


class PrependStreamProperties(SimpleTestCase):
    @given(
        prefix=st.binary(min_size=1, max_size=512),
        body=st.binary(max_size=2048),
        sizes=st.lists(st.integers(min_value=1, max_value=1024), max_size=60),
    )
    def test_arbitrary_read_sizes_reproduce_prefix_plus_body(self, prefix, body, sizes):
        """Concatenating arbitrary sized reads yields exactly prefix + body —
        lxml iterparse may call read() with any size."""
        stream = _PrependStream(prefix, io.BytesIO(body))
        out = bytearray()
        for size in sizes:
            chunk = stream.read(size)
            self.assertLessEqual(len(chunk), size)
            out.extend(chunk)
        out.extend(stream.read())
        self.assertEqual(bytes(out), prefix + body)

    @given(
        prefix=st.binary(min_size=1, max_size=512),
        body=st.binary(max_size=2048),
    )
    def test_full_read_is_prefix_plus_body(self, prefix, body):
        self.assertEqual(
            _PrependStream(prefix, io.BytesIO(body)).read(), prefix + body
        )


# ---------------------------------------------------------------------------
# detect_file_format
# ---------------------------------------------------------------------------


class DetectFileFormatProperties(SimpleTestCase):
    @given(body=st.binary(max_size=64))
    def test_gzip_magic_wins_over_extension(self, body):
        self.assertEqual(
            detect_file_format(file_path="guide.xml", content=b"\x1f\x8b" + body),
            ("gzip", True, ".gz"),
        )

    @given(body=st.binary(max_size=64))
    def test_xz_magic_wins_over_extension(self, body):
        self.assertEqual(
            detect_file_format(file_path="guide.gz", content=b"\xfd7zXZ\x00" + body),
            ("xz", True, ".xz"),
        )

    @given(body=st.binary(min_size=0, max_size=64))
    def test_zip_magic_is_detected(self, body):
        self.assertEqual(
            detect_file_format(content=b"PK" + body), ("zip", True, ".zip")
        )

    @given(
        name=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), blacklist_characters="."
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_compound_extension_prefers_compression(self, name):
        """``*.xml.gz`` is gzip, not xml — the final extension wins."""
        self.assertEqual(
            detect_file_format(file_path=f"{name}.xml.gz"), ("gzip", True, ".gz")
        )
        self.assertEqual(
            detect_file_format(file_path=f"{name}.xml.xz"), ("xz", True, ".xz")
        )
        self.assertEqual(
            detect_file_format(file_path=f"{name}.XML"), ("xml", False, ".xml")
        )

    @given(
        content=st.one_of(st.none(), st.binary(max_size=64)),
        path=st.one_of(st.none(), st.text(max_size=60)),
    )
    def test_arbitrary_input_never_raises_and_stays_in_vocabulary(self, content, path):
        fmt, compressed, ext = detect_file_format(file_path=path, content=content)
        self.assertIn(fmt, ("gzip", "zip", "xz", "xml", "unknown"))
        self.assertIsInstance(compressed, bool)
        self.assertTrue(ext.startswith("."))
        self.assertEqual(compressed, fmt in ("gzip", "zip", "xz"))


# ---------------------------------------------------------------------------
# parse_text_query
# ---------------------------------------------------------------------------

term_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"), blacklist_characters='"()'
    ),
    max_size=40,
)

# Characters whose upper() grows (e.g. 'ŉ' -> 'ʼN') or shrinks ('ß' -> 'SS')
# shift the byte offsets the operator scan derives from upper() back into the
# original string, mis-slicing the very next token. That is case-conflation
# behaviour the parser documents for operator words themselves; excluded here
# so the term-construction properties don't depend on it.
def _is_case_stable(term):
    return all(len(c.upper()) == 1 for c in term)


class ParseTextQueryProperties(SimpleTestCase):
    @given(raw=st.text(max_size=200))
    def test_arbitrary_input_builds_a_q_object(self, raw):
        """Untrusted search text never raises and always yields a Q."""
        q = parse_text_query("title", raw)
        self.assertIsInstance(q, Q)

    @given(term=term_text)
    def test_bare_term_is_a_single_icontains(self, term):
        """A term with no operators is one icontains lookup (or empty Q)."""
        assume(term.strip())
        assume(_is_case_stable(term))
        assume(" AND " not in term.upper() and " OR " not in term.upper())
        q = parse_text_query("title", term)
        self.assertEqual(q, Q(**{"title__icontains": term.strip()}))

    @given(phrase=st.text(min_size=1, max_size=60))
    def test_quoted_phrase_stays_atomic(self, phrase):
        """Operators inside double quotes are never split.

        Quotes inside the phrase would terminate it early, so generate phrases
        without them; nested-quote handling is exercised by the no-raise test.
        """
        assume('"' not in phrase)
        # build_q_object strips the phrase; whitespace-only/padded phrases
        # therefore land on icontains('').
        assume(phrase.strip())
        q = parse_text_query("title", f'"{phrase}"')
        self.assertEqual(q, Q(**{"title__icontains": phrase.strip()}))

    @given(a=term_text, b=term_text)
    def test_and_splits_into_conjunction(self, a, b):
        assume(a.strip() and b.strip())
        assume(_is_case_stable(a) and _is_case_stable(b))
        # 'AND'/'OR' inside a trailing token of `a` or a leading token of `b`
        # would merge with the injected operator; exclude the prefix/suffix
        # forms rather than forbidding the words anywhere in the term.
        for banned in ("AND", "OR"):
            assume(not a.upper().endswith(" " + banned))
            assume(not b.upper().startswith(banned + " "))
        q = parse_text_query("title", f"{a} AND {b}")
        self.assertEqual(
            q, Q(**{"title__icontains": a.strip()}) & Q(**{"title__icontains": b.strip()})
        )


# ---------------------------------------------------------------------------
# sd_credential_fingerprint
# ---------------------------------------------------------------------------

cred_text = st.one_of(st.none(), st.text(max_size=100))


class CredentialFingerprintProperties(SimpleTestCase):
    @given(username=cred_text, password=cred_text)
    def test_deterministic(self, username, password):
        self.assertEqual(
            sd_credential_fingerprint(username, password),
            sd_credential_fingerprint(username, password),
        )
        self.assertEqual(len(sd_credential_fingerprint(username, password)), 64)

    @given(username=cred_text, password=cred_text)
    def test_none_normalizes_to_empty_and_strip_is_applied(self, username, password):
        """None, '' and whitespace-padded forms of the same value match."""
        fp = sd_credential_fingerprint(username, password)
        self.assertEqual(
            fp,
            sd_credential_fingerprint((username or "").strip(), (password or "").strip()),
        )

    @given(
        u1=st.text(min_size=1, max_size=50),
        u2=st.text(min_size=1, max_size=50),
        password=cred_text,
    )
    def test_distinct_credentials_give_distinct_fingerprints(self, u1, u2, password):
        """A username change invalidates the cached token/lockout (SHA-256)."""
        assume(u1.strip() != u2.strip())
        self.assertNotEqual(
            sd_credential_fingerprint(u1, password),
            sd_credential_fingerprint(u2, password),
        )
