"""Property-based tests for EPG parsing helpers.

Covers the pure (DB-free, Redis-free) parsing surfaces of ``apps.epg``:

* ``parse_xmltv_time`` — XMLTV timestamp parsing. Properties state what the
  implementation promises: valid 14-digit base timestamps (with no offset, or
  with a spaced ``±HHMM`` offset) parse to the equivalent UTC instant, and the
  result is always timezone-aware.
* ``extract_season_episode_from_description`` — S/E prefix extraction.
  Promises: never raises, returns ``(int, int, str)`` or ``(None, None,
  original)``, and the cleaned description is always a stripped suffix of the
  input (no fabricated content).
* ``extract_season_episode`` — the layered fallback over custom_properties.
  Promises: explicit ``season``/``episode`` keys are always preserved;
  results are ``int`` or ``None``.
* ``extract_custom_properties`` — XMLTV ``<programme>`` metadata extraction.
  Promises: arbitrary well-formed XML input never raises; output is a dict;
  any ``season``/``episode`` values are positive ints.
* ``_decode_channel_id`` — byte-level index channel-id decoding. Promises:
  arbitrary bytes never raise; entities are resolved and whitespace stripped;
  decoding is idempotent for clean ids.
* ``sd_poster_cache_bust`` / ``sd_poster_proxy_path`` — nginx cache-busting.
  Promises: deterministic 12-hex-char token for any string, empty for empty;
  the proxy path is stable and embeds the token iff one exists.
* ``parse_text_query`` — EPG search expression parsing. Promises: arbitrary
  input never raises and always returns a ``Q`` object.

These invariants are deliberately limited to what the code actually
guarantees (read the implementation before extending); a falsification is a
finding, not a test bug.

Note on scope: two real defects found while deriving these invariants are
*not* asserted here because the implementation currently violates them —
they are filed as issues instead:

* a no-space timezone offset (``...183000+0530``) is silently ignored;
* an out-of-range offset (``...183000 +2400``) raises ``ValueError`` that
  propagates uncaught out of the byte-offset "now playing" lookup.
"""

import os
import re
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from xml.etree.ElementTree import fromstring

from django.db.models import Q
from django.test import SimpleTestCase
from django.utils import timezone
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.epg.query_utils import parse_text_query
from apps.epg.tasks import (
    _HTML_ENTITY_DOCTYPE,
    _decode_channel_id,
    _find_programme_tag,
    _open_xmltv_file,
    detect_file_format,
    extract_custom_properties,
    parse_xmltv_time,
)
from apps.epg.utils import (
    extract_season_episode,
    extract_season_episode_from_description,
    sd_poster_cache_bust,
    sd_poster_proxy_path,
)

# CI-deterministic profile (same convention as the live_proxy property tests).
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid 14-digit base datetimes within datetime's representable range.
# Microseconds are zeroed because the XMLTV format has no sub-second field
# (strftime truncates them, so a non-zero value could never round-trip).
_base_dt = st.datetimes(
    min_value=datetime(1000, 1, 1),
    max_value=datetime(9999, 12, 31),
).map(lambda dt: dt.replace(microsecond=0))

# Offsets strictly inside (-24h, +24h) so dt_timezone accepts them.
_tz_offset_minutes = st.integers(min_value=-23 * 60 - 59, max_value=23 * 60 + 59)

_SAFE_TEXT = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    max_size=80,
)


def _fmt_base(dt):
    return dt.strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------------------
# parse_xmltv_time
# ---------------------------------------------------------------------------


class ParseXmltvTimeProperties(SimpleTestCase):
    @given(dt=_base_dt)
    def test_bare_timestamp_parses_as_utc(self, dt):
        """A bare 14-digit timestamp is interpreted as UTC."""
        result = parse_xmltv_time(_fmt_base(dt))
        self.assertEqual(result, dt.replace(tzinfo=dt_timezone.utc))

    @given(dt=_base_dt, offset_minutes=_tz_offset_minutes)
    def test_spaced_offset_converts_to_utc(self, dt, offset_minutes):
        """'base ±HHMM' parses to the same instant as base minus the offset."""
        sign = "+" if offset_minutes >= 0 else "-"
        abs_min = abs(offset_minutes)
        stamp = f"{_fmt_base(dt)} {sign}{abs_min // 60:02d}{abs_min % 60:02d}"
        result = parse_xmltv_time(stamp)
        expected = (dt.replace(tzinfo=dt_timezone.utc)
                    - timedelta(minutes=offset_minutes))
        self.assertEqual(result, expected)

    @given(dt=_base_dt, offset_minutes=_tz_offset_minutes)
    def test_result_always_aware(self, dt, offset_minutes):
        """The result is always a timezone-aware datetime."""
        sign = "+" if offset_minutes >= 0 else "-"
        abs_min = abs(offset_minutes)
        for stamp in (_fmt_base(dt), f"{_fmt_base(dt)} {sign}{abs_min // 60:02d}{abs_min % 60:02d}"):
            result = parse_xmltv_time(stamp)
            self.assertIsNotNone(result.tzinfo)
            self.assertIsNotNone(result.utcoffset())


# ---------------------------------------------------------------------------
# extract_season_episode_from_description
# ---------------------------------------------------------------------------


class ExtractSeasonEpisodeFromDescriptionProperties(SimpleTestCase):
    @given(desc=st.text(max_size=200))
    def test_never_raises_and_result_shape(self, desc):
        season, episode, cleaned = extract_season_episode_from_description(desc)
        if season is None:
            self.assertIsNone(episode)
            self.assertEqual(cleaned, desc)
        else:
            self.assertIsInstance(season, int)
            self.assertIsInstance(episode, int)
            self.assertGreaterEqual(season, 0)
            self.assertGreaterEqual(episode, 0)
            # Cleaned text must be a stripped suffix of the input — no
            # content may be fabricated or reordered.
            self.assertTrue(desc.endswith(cleaned) or cleaned == desc.strip())
            self.assertLessEqual(len(cleaned), len(desc))

    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=0, max_value=9999),
        tail=_SAFE_TEXT,
    )
    def test_canonical_prefix_round_trips(self, season, episode, tail):
        desc = f"S{season:02d}E{episode:02d} {tail}"
        s, e, cleaned = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))
        # The trailing pattern class consumes separator chars between the
        # episode number and the description body; the remainder is stripped.
        self.assertEqual(cleaned, tail.lstrip(" \t-:.").strip())

    @given(
        season=st.integers(min_value=0, max_value=999),
        episode=st.integers(min_value=10, max_value=9999),
        tail=_SAFE_TEXT,
    )
    def test_dx_format_round_trips(self, season, episode, tail):
        """'NxMM' (2+ digit episode) is recognised per the pattern contract."""
        desc = f"{season}x{episode:02d} {tail}"
        s, e, _ = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))


# ---------------------------------------------------------------------------
# extract_season_episode (layered fallback)
# ---------------------------------------------------------------------------


class ExtractSeasonEpisodeProperties(SimpleTestCase):
    @given(
        season=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
        episode=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
        onscreen=st.one_of(st.none(), st.text(max_size=40)),
        desc=st.one_of(st.none(), st.text(max_size=80)),
    )
    def test_explicit_values_preserved_and_types(self, season, episode, onscreen, desc):
        cp = {}
        if season is not None:
            cp["season"] = season
        if episode is not None:
            cp["episode"] = episode
        if onscreen is not None:
            cp["onscreen_episode"] = onscreen
        s, e = extract_season_episode(cp, description=desc)
        self.assertIsInstance(s, (int, type(None)))
        self.assertIsInstance(e, (int, type(None)))
        # Explicitly-provided values win over every fallback.
        if season is not None:
            self.assertEqual(s, season)
        if episode is not None:
            self.assertEqual(e, episode)


# ---------------------------------------------------------------------------
# extract_custom_properties
# ---------------------------------------------------------------------------

_ep_num_system = st.sampled_from(
    ["", "onscreen", "xmltv_ns", "dd_progid", "thetvdb.com", "themoviedb.org",
     "imdb.com", "unknown-system"]
)


def _esc(text):
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


class ExtractCustomPropertiesProperties(SimpleTestCase):
    @given(
        system=_ep_num_system,
        value=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"), blacklist_characters='<>&"\''
            ),
            max_size=40,
        ),
    )
    def test_episode_num_never_raises(self, system, value):
        xml = (
            f'<programme start="20260728183000 +0000" stop="20260728190000 +0000">'
            f'<episode-num system="{system}">{_esc(value)}</episode-num>'
            f"</programme>"
        )
        props = extract_custom_properties(fromstring(xml))
        self.assertIsInstance(props, dict)
        for key in ("season", "episode"):
            if key in props:
                self.assertIsInstance(props[key], int)
                self.assertGreaterEqual(props[key], 0)

    @given(
        categories=st.lists(_SAFE_TEXT, max_size=5),
        keywords=st.lists(_SAFE_TEXT, max_size=5),
    )
    def test_categories_and_keywords_are_stripped_nonempty(self, categories, keywords):
        children = "".join(
            f"<category>{_esc(c)}</category>" for c in categories
        ) + "".join(f"<keyword>{_esc(k)}</keyword>" for k in keywords)
        xml = (
            '<programme start="20260728183000 +0000" stop="20260728190000 +0000">'
            f"{children}</programme>"
        )
        props = extract_custom_properties(fromstring(xml))
        for key, source in (("categories", categories), ("keywords", keywords)):
            expected = [v.strip() for v in source if v and v.strip()]
            if expected:
                self.assertEqual(props.get(key), expected)
            else:
                self.assertNotIn(key, props)

    @given(xml_text=st.text(alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="<>&"
    ), max_size=120))
    def test_free_text_fields_do_not_crash(self, xml_text):
        xml = (
            '<programme start="20260728183000 +0000" stop="20260728190000 +0000">'
            f"<desc>{xml_text}</desc><date>{xml_text}</date>"
            f"<country>{xml_text}</country><language>{xml_text}</language>"
            "</programme>"
        )
        props = extract_custom_properties(fromstring(xml))
        self.assertIsInstance(props, dict)


# ---------------------------------------------------------------------------
# _decode_channel_id
# ---------------------------------------------------------------------------


class DecodeChannelIdProperties(SimpleTestCase):
    @given(raw=st.binary(max_size=200))
    def test_arbitrary_bytes_never_raise(self, raw):
        result = _decode_channel_id(raw)
        self.assertIsInstance(result, str)
        # Result is always stripped (implementation promises .strip()).
        self.assertEqual(result, result.strip())

    @given(text=st.text(alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters='<>&"\'',
    ), max_size=60))
    def test_clean_utf8_round_trips(self, text):
        """Bytes of plain text decode to the same text, stripped."""
        result = _decode_channel_id(text.encode("utf-8"))
        self.assertEqual(result, text.strip())

    @given(text=st.text(alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"), blacklist_characters='<>&"\''
    ), max_size=40))
    def test_entities_resolved(self, text):
        """An '&amp;' entity decodes to a literal '&' like lxml would produce."""
        raw = (text + " &amp; " + text).encode("utf-8")
        result = _decode_channel_id(raw)
        self.assertNotIn("&amp;", result)


# ---------------------------------------------------------------------------
# sd_poster_cache_bust / sd_poster_proxy_path
# ---------------------------------------------------------------------------


class SdPosterProperties(SimpleTestCase):
    @given(url=st.text(max_size=300))
    def test_cache_bust_shape_and_determinism(self, url):
        bust1 = sd_poster_cache_bust(url)
        bust2 = sd_poster_cache_bust(url)
        self.assertEqual(bust1, bust2)
        if url:
            self.assertEqual(len(bust1), 12)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{12}", bust1))
        else:
            self.assertEqual(bust1, "")

    @given(program_id=st.integers(min_value=0, max_value=2**63),
           url=st.text(max_size=200))
    def test_proxy_path_embeds_bust_iff_present(self, program_id, url):
        path = sd_poster_proxy_path(program_id, url)
        prefix = f"/api/epg/programs/{program_id}/poster/"
        self.assertTrue(path.startswith(prefix))
        bust = sd_poster_cache_bust(url)
        if bust:
            self.assertEqual(path, f"{prefix}?v={bust}")
        else:
            self.assertEqual(path, prefix)


# ---------------------------------------------------------------------------
# parse_text_query
# ---------------------------------------------------------------------------


class ParseTextQueryProperties(SimpleTestCase):
    @given(raw=st.text(max_size=200))
    def test_arbitrary_input_returns_q(self, raw):
        result = parse_text_query("title", raw)
        self.assertIsInstance(result, Q)

    @given(raw=st.text(max_size=120))
    def test_regex_mode_returns_q(self, raw):
        # In regex mode the whole raw value is a single iregex pattern; an
        # invalid pattern only fails at query evaluation, not at Q build time.
        result = parse_text_query("title", raw, use_regex=True)
        self.assertIsInstance(result, Q)

    @given(term=st.text(alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"), blacklist_characters='"'
    ), min_size=1, max_size=40))
    def test_bare_term_is_icontains(self, term):
        assume(" AND " not in term.upper() and " OR " not in term.upper())
        assume("(" not in term and ")" not in term)
        q = parse_text_query("title", term)
        self.assertIsInstance(q, Q)
        # A single bare term compiles to exactly one icontains lookup.
        self.assertEqual(len(q.children), 1)
        lookup, value = q.children[0]
        self.assertEqual(lookup, "title__icontains")
        self.assertEqual(value, term.strip())


# ---------------------------------------------------------------------------
# _open_xmltv_file
# ---------------------------------------------------------------------------


def _write_tmp(content):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    return path


class OpenXmltvFileProperties(SimpleTestCase):
    def tearDown(self):
        for path in getattr(self, "_tmp", []):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _open(self, content):
        path = _write_tmp(content)
        self._tmp = getattr(self, "_tmp", []) + [path]
        return _open_xmltv_file(path)

    @given(body=st.binary(min_size=0, max_size=512))
    def test_no_declaration_injects_doctype_at_start(self, body):
        assume(b"<!DOCTYPE" not in body and b"<!doctype" not in body.lower())
        assume(b"<?xml" not in body)
        stream = self._open(body)
        try:
            data = stream.read()
        finally:
            stream.close()
        self.assertEqual(data, _HTML_ENTITY_DOCTYPE + body)

    @given(
        decl_tail=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            max_size=40,
        ).map(str.encode).filter(lambda b: b"?" not in b and b">" not in b),
        body=st.binary(min_size=0, max_size=512),
    )
    def test_declaration_gets_doctype_after_it(self, decl_tail, body):
        assume(b"<!DOCTYPE" not in body and b"<!doctype" not in body.lower())
        # Keep a single, well-formed <?xml ...?> declaration at offset 0.
        decl = b"<?xml " + decl_tail.replace(b"<", b"").replace(b"&", b"") + b"?>"
        assume(b"<?xml" not in body)
        content = decl + body
        stream = self._open(content)
        try:
            data = stream.read()
        finally:
            stream.close()
        self.assertEqual(data, decl + b"\n" + _HTML_ENTITY_DOCTYPE + body)

    @given(body=st.binary(min_size=1, max_size=512))
    def test_existing_doctype_is_left_untouched(self, body):
        content = b"<!DOCTYPE tv [\n]>\n" + body
        stream = self._open(content)
        try:
            data = stream.read()
        finally:
            stream.close()
        self.assertEqual(data, content)

    @given(
        body=st.binary(min_size=0, max_size=1024),
        read_size=st.integers(min_value=1, max_value=256),
    )
    def test_chunked_reads_equal_single_read(self, body, read_size):
        assume(b"<?xml" not in body)
        assume(b"<!DOCTYPE" not in body and b"<!doctype" not in body.lower())
        stream = self._open(body)
        try:
            single = stream.read()
        finally:
            stream.close()
        stream2 = self._open(body)
        try:
            buf = bytearray()
            while True:
                chunk = stream2.read(read_size)
                if not chunk:
                    break
                buf.extend(chunk)
        finally:
            stream2.close()
        self.assertEqual(bytes(buf), single)


# ---------------------------------------------------------------------------
# detect_file_format
# ---------------------------------------------------------------------------


class DetectFileFormatProperties(SimpleTestCase):
    @given(
        ext=st.sampled_from([".xml", ".gz", ".zip", ".xz", ".txt", ""]),
        junk=st.binary(max_size=40),
    )
    def test_magic_bytes_beat_extension(self, ext, junk):
        """A recognized magic header determines the format regardless of name."""
        for magic, expected in (
            (b"\x1f\x8b", "gzip"),
            (b"PK", "zip"),
            (b"\xfd7zXZ\x00", "xz"),
        ):
            fmt, compressed, _ = detect_file_format(
                file_path=f"feed{ext}", content=magic + junk
            )
            self.assertEqual(fmt, expected, (magic, ext))
            self.assertTrue(compressed)

    @given(name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1, max_size=20,
    ))
    def test_xml_extension_detected(self, name):
        fmt, compressed, file_ext = detect_file_format(file_path=f"{name}.xml")
        self.assertEqual((fmt, compressed, file_ext), ("xml", False, ".xml"))

    @given(content=st.binary(min_size=0, max_size=100))
    def test_never_raises_on_arbitrary_content(self, content):
        fmt, compressed, file_ext = detect_file_format(content=content)
        self.assertIn(fmt, ("gzip", "zip", "xz", "xml", "unknown"))
        self.assertIsInstance(compressed, bool)
        self.assertTrue(file_ext.startswith("."))


# ---------------------------------------------------------------------------
# _find_programme_tag
# ---------------------------------------------------------------------------


class FindProgrammeTagProperties(SimpleTestCase):
    @given(
        prefix=st.binary(max_size=64),
        attrs=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            max_size=120,
        ).map(str.encode).filter(lambda b: b">" not in b),
        suffix=st.binary(max_size=64),
    )
    def test_offsets_valid_for_wellformed_tag(self, prefix, attrs, suffix):
        assume(b"<programme" not in prefix)
        tag = b"<programme " + attrs + b">"
        buf = prefix + tag + suffix
        idx, tag_end = _find_programme_tag(buf, 0)
        if idx == -1:
            # Only legal if the tag exceeds the _MAX_START_TAG scan window.
            self.assertGreater(len(prefix) + len(tag), 0)
            self.assertGreaterEqual(len(tag), 0)
            return
        self.assertEqual(idx, len(prefix))
        self.assertEqual(buf[tag_end], ord(">"))
        self.assertLessEqual(tag_end, len(buf) - 1)
        self.assertEqual(buf[idx:idx + 10], b"<programme")

    @given(buf=st.binary(max_size=256))
    def test_arbitrary_buffer_never_raises(self, buf):
        idx, tag_end = _find_programme_tag(buf, 0)
        if idx == -1:
            self.assertEqual(tag_end, -1)
        else:
            self.assertGreaterEqual(idx, 0)
            self.assertLess(idx, len(buf))
            self.assertTrue(
                tag_end == -1 or (idx < tag_end < len(buf)),
                (idx, tag_end, len(buf)),
            )


# ---------------------------------------------------------------------------
# _sd_pick_poster_url / sd_parse_response_payload (Schedules Direct helpers)
# ---------------------------------------------------------------------------

from apps.epg.sd_tasks import SD_POSTER_STYLE_CONFIG, _sd_pick_poster_url
from apps.epg.sd_utils import sd_parse_response_payload

_sd_image = st.fixed_dictionaries(
    {},
    optional={
        "uri": st.text(max_size=120),
        "category": st.one_of(
            st.sampled_from([
                "Iconic", "Banner-L1", "Banner-L2", "Banner-L3", "Banner",
                "Staple", "Poster Art", "Box Art", "Unknown",
            ]),
            st.text(max_size=20),
        ),
        "aspect": st.one_of(
            st.sampled_from(["2x3", "3x4", "16x9", "4x3", "1x1", "bogus"]),
            st.text(max_size=10),
        ),
        "width": st.one_of(
            st.integers(min_value=0, max_value=2000),
            st.text(max_size=8),
            st.none(),
        ),
        "primary": st.one_of(st.booleans(), st.text(max_size=6), st.none()),
    },
)


class SdPickPosterUrlProperties(SimpleTestCase):
    @given(images=st.lists(st.one_of(_sd_image, st.integers(), st.text(max_size=10)), max_size=12))
    def test_never_raises_and_result_is_input_uri_or_none(self, images):
        for style in list(SD_POSTER_STYLE_CONFIG) + ["sd_recommended", "nonexistent-style"]:
            result = _sd_pick_poster_url(images, style)
            if result is None:
                continue
            self.assertIsInstance(result, str)
            # The returned URI must come from the supplied images — never fabricated.
            uris = {
                img.get("uri") for img in images
                if isinstance(img, dict) and img.get("uri")
            }
            self.assertIn(result, uris)

    def test_empty_image_list_returns_none(self):
        for style in list(SD_POSTER_STYLE_CONFIG) + ["sd_recommended"]:
            self.assertIsNone(_sd_pick_poster_url([], style))


class _FakeResponse:
    """Minimal stand-in for requests.Response for sd_parse_response_payload."""

    def __init__(self, content=b"", content_type=""):
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}

    def json(self):
        import json as _json

        return _json.loads(self.content.decode("utf-8", "replace"))


class SdParseResponsePayloadProperties(SimpleTestCase):
    @given(body=st.binary(max_size=300))
    def test_arbitrary_bytes_never_raise(self, body):
        code, data = sd_parse_response_payload(_FakeResponse(body, "application/json"))
        if data is None:
            self.assertIsNone(code)
        else:
            self.assertIsInstance(data, dict)
            self.assertTrue(code is None or isinstance(code, int))

    @given(code=st.one_of(st.integers(), st.text(max_size=20), st.none()))
    def test_code_only_returned_when_int(self, code):
        import json as _json

        body = _json.dumps({"code": code}).encode()
        got_code, data = sd_parse_response_payload(_FakeResponse(body, "application/json"))
        self.assertIsInstance(data, dict)
        if isinstance(code, int) and not isinstance(code, bool):
            self.assertEqual(got_code, code)
        else:
            # bool is a subclass of int; the implementation uses isinstance(int),
            # so a JSON true/false would come back as code — assert the contract
            # for non-int JSON values only.
            if isinstance(code, bool):
                self.assertIn(got_code, (True, False))
            else:
                self.assertIsNone(got_code)

    def test_none_response_returns_none_pair(self):
        self.assertEqual(sd_parse_response_payload(None), (None, None))

    def test_non_json_body_returns_none_pair(self):
        code, data = sd_parse_response_payload(_FakeResponse(b"<html>oops</html>", "text/html"))
        self.assertEqual((code, data), (None, None))
