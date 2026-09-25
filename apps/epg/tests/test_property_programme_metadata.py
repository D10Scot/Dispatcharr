"""Property-based tests for per-programme metadata extraction and file sniffing.

Surfaces (seed a54b09a9), all fed by provider XMLTV:

* ``extract_season_episode_from_description`` (apps/epg/utils.py:58) and
  ``extract_season_episode`` (:76) - the description/onscreen fallbacks.
* ``extract_custom_properties`` (apps/epg/tasks.py:2547) - runs on every
  programme of every refresh.
* ``_programme_to_dict`` (:2939) - the current-programme API's serializer.
* ``_parse_programme_element`` (:242) - the parser behind the offset lookups;
  both callers (``:3197``, ``:3291``) catch ``(etree.XMLSyntaxError,
  UnicodeDecodeError)`` and also skip a bare ``None`` result.
* ``detect_file_format`` (:2787) - magic bytes first, then the extension.
* ``validate_icon_url_fast`` (:325) - the icon-URL length guard.

Closes the metadata part of #202 (and duplicates #274, #158, #74).
"""

import html
import mimetypes
import re
import string
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg import tasks as epg_tasks
from apps.epg.models import EPGData
from apps.epg.tasks import (
    _parse_programme_element,
    _programme_to_dict,
    detect_file_format,
    extract_custom_properties,
    validate_icon_url_fast,
)
from apps.epg.utils import (
    extract_season_episode,
    extract_season_episode_from_description,
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

# Text sizes stay far below Python's 4300-digit int() limit on purpose: a
# longer digit run raises ValueError from the unguarded int() calls, which is
# not a realistic provider value.
_SEP = st.sampled_from(["", " ", "-", ": ", " - ", ".", "  "])
# A rest that starts with a digit would extend the greedy episode number.
_REST = st.text(max_size=60).filter(lambda r: not re.match(r"\d", r))


# ---------------------------------------------------------------------------
# Season/episode from description
# ---------------------------------------------------------------------------

class SeasonEpisodeFromDescriptionProperties(SimpleTestCase):
    @given(desc=st.one_of(st.none(), st.text(max_size=120)))
    def test_a_description_is_either_untouched_or_cut_to_a_stripped_suffix(
        self, desc
    ):
        season, episode, cleaned = extract_season_episode_from_description(desc)
        if season is None:
            self.assertIsNone(episode)
            self.assertIs(cleaned, desc)  # returned unchanged, same object
            return
        self.assertIsInstance(season, int)
        self.assertIsInstance(episode, int)
        # It can only cut a recognised prefix, never invent text.
        self.assertTrue(desc.rstrip().endswith(cleaned))
        self.assertEqual(cleaned, cleaned.strip())

    @given(
        form=st.sampled_from(["S{s}E{e}", "s{s} e{e}", "Season {s} Episode {e}",
                              "season{s}episode{e}", "{s}x{e:02d}"]),
        season=st.integers(0, 999),
        episode=st.integers(10, 9999),
        lead=st.sampled_from(["", " ", "- ", ": "]),
        sep=_SEP,
        rest=_REST,
    )
    def test_every_documented_prefix_form_round_trips(
        self, form, season, episode, lead, sep, rest
    ):
        desc = lead + form.format(s=season, e=episode) + sep + rest
        s, e, _ = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))

    @given(season=st.integers(0, 99), episode=st.integers(0, 9), rest=_REST)
    def test_a_single_digit_nx_episode_is_not_recognised(self, season, episode, rest):
        # The 1x01 form requires a 2+ digit episode (utils.py:28-29) so that
        # text like "4x4 rally" is not read as season 4 episode 4.
        s, e, cleaned = extract_season_episode_from_description(
            f"{season}x{episode} {rest}".replace("S", "").replace("s", "")
        )
        self.assertEqual((s, e), (None, None))


class ExtractSeasonEpisodeProperties(SimpleTestCase):
    @given(
        season=st.one_of(st.none(), st.integers(0, 500)),
        episode=st.one_of(st.none(), st.integers(0, 5000)),
        on_s=st.integers(0, 500),
        on_e=st.integers(0, 5000),
        d_s=st.integers(0, 500),
        d_e=st.integers(0, 5000),
    )
    def test_explicit_fields_win_then_onscreen_then_description(
        self, season, episode, on_s, on_e, d_s, d_e
    ):
        cp = {"season": season, "episode": episode,
              "onscreen_episode": f"S{on_s} E{on_e}"}
        s, e = extract_season_episode(cp, f"S{d_s}E{d_e} rest")
        self.assertEqual(s, season if season is not None else on_s)
        self.assertEqual(e, episode if episode is not None else on_e)

    @given(
        season=st.one_of(st.none(), st.integers(0, 500)),
        episode=st.one_of(st.none(), st.integers(0, 5000)),
        d_s=st.integers(0, 500),
        d_e=st.integers(0, 5000),
        onscreen=st.sampled_from([None, "", "Part 2", "E5"]),
    )
    def test_the_description_fills_only_the_missing_half(
        self, season, episode, d_s, d_e, onscreen
    ):
        cp = {"season": season, "episode": episode}
        if onscreen is not None:
            cp["onscreen_episode"] = onscreen  # present but unmatched
        s, e = extract_season_episode(cp, f"S{d_s}E{d_e} rest")
        self.assertEqual(s, season if season is not None else d_s)
        self.assertEqual(e, episode if episode is not None else d_e)


# ---------------------------------------------------------------------------
# extract_custom_properties / _programme_to_dict / _parse_programme_element
# ---------------------------------------------------------------------------

_TEXT_ALPHABET = string.ascii_letters + string.digits + " \t-_.:,;!?()[]#'\"/\\é"
xml_text = st.text(alphabet=_TEXT_ALPHABET, max_size=40)
_SYSTEMS = st.sampled_from(
    [None, "", "xmltv_ns", "onscreen", "dd_progid", "imdb.com", "thetvdb.com",
     "themoviedb.org", "SxxExx", "other"]
)
_SIMPLE_TAGS = st.sampled_from(
    ["category", "keyword", "date", "country", "language", "orig-language",
     "length", "premiere", "last-chance", "new", "live", "previously-shown",
     "review", "image", "title", "desc", "sub-title", "bogus"]
)


def _attr(name, value):
    return "" if value is None else f' {name}="{html.escape(value, quote=True)}"'


def _el(tag, text="", **attrs):
    a = "".join(_attr(k.replace("_", "-"), v) for k, v in attrs.items())
    return f"<{tag}{a}>{html.escape(text, quote=False)}</{tag}>"


children = st.lists(
    st.one_of(
        st.builds(lambda t, x: _el(t, x), _SIMPLE_TAGS, xml_text),
        st.builds(lambda s, x: _el("episode-num", x, system=s), _SYSTEMS, xml_text),
        st.builds(lambda x, s: "<rating" + _attr("system", s) + ">" + _el("value", x) + "</rating>",
                  xml_text, st.one_of(st.none(), xml_text)),
        st.builds(lambda x: "<star-rating>" + _el("value", x) + "</star-rating>", xml_text),
        st.builds(lambda t, x, r: "<credits>" + _el(t, x, role=r) + "</credits>",
                  st.sampled_from(["director", "actor", "writer", "presenter", "guest"]),
                  xml_text, st.one_of(st.none(), xml_text)),
        st.builds(lambda k, x: "<video>" + _el(k, x) + "</video>",
                  st.sampled_from(["present", "colour", "aspect", "quality"]), xml_text),
        st.builds(lambda x: "<audio>" + _el("stereo", x) + "</audio>", xml_text),
        st.builds(lambda t, x: "<subtitles" + _attr("type", t) + ">" + _el("language", x) + "</subtitles>",
                  st.one_of(st.none(), xml_text), xml_text),
        st.builds(lambda s: "<icon" + _attr("src", s) + "/>", st.one_of(st.none(), xml_text)),
        st.builds(lambda x, u: _el("length", x, units=u), xml_text,
                  st.one_of(st.none(), st.sampled_from(["minutes", "seconds"]))),
    ),
    max_size=14,
).map("".join)


def _programme(inner):
    return etree.fromstring(f"<programme>{inner}</programme>")


class ExtractCustomPropertiesProperties(SimpleTestCase):
    @given(inner=children)
    def test_any_wellformed_programme_yields_the_documented_types(self, inner):
        props = extract_custom_properties(_programme(inner))
        self.assertIsInstance(props, dict)
        for key in ("season", "episode"):
            if key in props:
                self.assertIsInstance(props[key], int)
        for key in ("categories", "keywords"):
            if key in props:
                self.assertTrue(props[key])
                for item in props[key]:
                    self.assertTrue(item)
                    self.assertEqual(item, item.strip())
        if "length" in props:
            self.assertIsInstance(props["length"]["value"], int)
            self.assertIsInstance(props["length"]["units"], str)

    # Totals-free form only: the XMLTV DTD also allows "s/total . e/total",
    # which int() refuses, so the season is silently dropped (plan I
    # finding F-3).
    @given(
        season=st.integers(0, 500),
        episode=st.integers(0, 5000),
        part=st.sampled_from(["", "0", "1"]),
        pad=st.sampled_from(["", " "]),
    )
    def test_xmltv_ns_is_zero_based_and_stored_one_based(
        self, season, episode, part, pad
    ):
        text = f"{pad}{season}{pad}.{pad}{episode}{pad}.{part}"
        props = extract_custom_properties(
            _programme(_el("episode-num", text, system="xmltv_ns"))
        )
        self.assertEqual(props["season"], season + 1)
        self.assertEqual(props["episode"], episode + 1)

    @given(
        ns_season=st.integers(0, 50),
        ns_episode=st.integers(0, 50),
        on_s=st.integers(0, 50),
        on_e=st.integers(0, 50),
        onscreen_first=st.booleans(),
    )
    def test_xmltv_ns_wins_over_onscreen_whatever_the_element_order(
        self, ns_season, ns_episode, on_s, on_e, onscreen_first
    ):
        ns = _el("episode-num", f"{ns_season}.{ns_episode}.", system="xmltv_ns")
        on = _el("episode-num", f"S{on_s}E{on_e}", system="onscreen")
        props = extract_custom_properties(_programme(on + ns if onscreen_first else ns + on))
        # xmltv_ns assigns unconditionally; onscreen only fills a missing key.
        self.assertEqual(props["season"], ns_season + 1)
        self.assertEqual(props["episode"], ns_episode + 1)
        self.assertEqual(props["onscreen_episode"], f"S{on_s}E{on_e}")

    @given(text=xml_text)
    def test_length_is_recorded_exactly_when_its_text_is_an_integer(self, text):
        props = extract_custom_properties(_programme(_el("length", text)))
        # int() also accepts single underscores between digits ("1_0" is 10).
        if re.fullmatch(r"\s*[+-]?\d+(?:_\d+)*\s*", text):
            self.assertEqual(props["length"], {"value": int(text), "units": "minutes"})
        else:
            self.assertNotIn("length", props)


class ProgrammeToDictProperties(SimpleTestCase):
    @given(
        inner=children,
        start=st.datetimes(timezones=st.just(dt_timezone.utc)),
        minutes=st.integers(0, 600),
    )
    def test_always_five_keys_with_string_text_and_iso_times(
        self, inner, start, minutes
    ):
        end = start + timedelta(minutes=minutes) if start.year < 9999 else start
        result = _programme_to_dict(_programme(inner), start, end)
        self.assertEqual(
            set(result), {"title", "description", "sub_title", "start_time", "end_time"}
        )
        for key in ("title", "description", "sub_title"):
            self.assertIsInstance(result[key], str)
        self.assertEqual(datetime.fromisoformat(result["start_time"]), start)
        self.assertEqual(datetime.fromisoformat(result["end_time"]), end)


_NAMED = ["eacute", "amp", "lt", "gt", "quot", "apos", "nbsp", "Uuml", "copy", "euro"]


class ParseProgrammeElementProperties(SimpleTestCase):
    @given(
        pieces=st.lists(
            st.one_of(
                st.text(alphabet=string.ascii_letters + " .", min_size=1, max_size=6),
                st.sampled_from(_NAMED).map(lambda n: f"&{n};"),
                # 0x7F-0x9F excluded: html.unescape remaps those per HTML5's
                # cp1252 table where XML keeps the code point; not this contract.
                st.integers(0x20, 0x2FFF).filter(lambda c: not 0x7F <= c <= 0x9F)
                .map(lambda c: f"&#{c};"),
            ),
            max_size=10,
        )
    )
    def test_html4_and_numeric_entities_resolve_as_html_unescape_does(self, pieces):
        text = "".join(pieces)
        elem = _parse_programme_element(
            f"<programme><title>{text}</title></programme>".encode()
        )
        self.assertEqual(elem.findtext("title") or "", html.unescape(text))

    @given(raw=st.one_of(
        st.binary(max_size=120),
        st.lists(st.sampled_from(
            [b"<programme>", b"</programme>", b"<title>", b"</title>", b"&", b";",
             b"&eacute;", b"&NewLine;", b"&#0;", b"&#xD800;", b"<", b">", b"x",
             b"\xff", b"]]>", b"<!--", b"<![CDATA["]), max_size=15).map(b"".join),
    ))
    def test_any_bytes_either_parse_return_none_or_raise_a_caught_parse_error_only(self, raw):
        # Three outcomes, and nothing else, may escape _parse_programme_element:
        # an Element, a bare None, or one of the exceptions both call sites
        # catch, (etree.XMLSyntaxError, UnicodeDecodeError) at
        # apps/epg/tasks.py:3285, :3394. C-2 (#420, round 2) parses with
        # recover=True, so libxml2 does not raise when it cannot find a root
        # element -- it returns None instead, which both callers already
        # handle (`if prog is None: continue`). C-2 (#420, rounds 3-5) also
        # forces a decode with etree.tostring() so a lone UTF-16 surrogate
        # character reference anywhere in the element (e.g. &#xD800;) raises
        # UnicodeDecodeError at parse time instead of later, out of the
        # result-building code -- the second member of that same except
        # tuple. The property's intent -- no exception type escapes other
        # than the ones the callers already catch -- is unchanged; the
        # excused set now mirrors that except tuple exactly, and the set of
        # non-raising values is widened to match recover=True.
        try:
            elem = _parse_programme_element(raw)
        except (etree.XMLSyntaxError, UnicodeDecodeError):
            return
        self.assertTrue(
            elem is None or isinstance(elem, etree._Element),
            f"expected an Element, None, or a caught parse error; got {elem!r}",
        )

    def test_recover_mode_returns_none_for_unrecoverable_bytes_and_an_element_otherwise(self):
        # Deterministic pin of the None contract the property above only
        # checks the type of (C-2, #420, round 2's recover=True). Four bytes
        # strings from which libxml2 cannot recover a root element; one that
        # it can.
        for raw in (b"", b"x", b"<", b">>>"):
            with self.subTest(raw=raw):
                self.assertIsNone(_parse_programme_element(raw))
        elem = _parse_programme_element(b"<programme>")
        self.assertIsNotNone(elem)
        self.assertEqual(elem.tag, "programme")

        # Deterministic pin of the UnicodeDecodeError contract the property
        # above only checks the type of (C-2, #420, rounds 3-5's forced
        # etree.tostring() decode). A lone UTF-16 surrogate character
        # reference anywhere in the element raises at parse time rather than
        # later, out of the result-building code.
        with self.assertRaises(UnicodeDecodeError):
            _parse_programme_element(b"<_>&#xD800;")


# ---------------------------------------------------------------------------
# detect_file_format / validate_icon_url_fast
# ---------------------------------------------------------------------------

_FORMATS = {
    "gzip": (True, ".gz"), "zip": (True, ".zip"), "xz": (True, ".xz"),
    "xml": (False, ".xml"), "unknown": (False, ".tmp"),
}
_MAGIC = [(b"\x1f\x8b", "gzip"), (b"PK", "zip"), (b"\xfd7zXZ\x00", "xz")]
_EXTS = [(".gz", "gzip"), (".gzip", "gzip"), (".zip", "zip"), (".xz", "xz"),
         (".xml", "xml")]
_names = st.text(alphabet=string.ascii_letters + string.digits + "._-/", max_size=20)


class DetectFileFormatProperties(SimpleTestCase):
    @given(
        content=st.one_of(st.none(), st.binary(max_size=64)),
        path=st.one_of(st.none(), st.text(max_size=40)),
    )
    def test_the_result_is_always_a_consistent_vocabulary_triple(self, content, path):
        fmt, compressed, ext = detect_file_format(file_path=path, content=content)
        self.assertEqual((compressed, ext), _FORMATS[fmt])

    @given(
        magic=st.sampled_from(_MAGIC),
        tail=st.binary(max_size=40),
        name=_names,
        ext=st.sampled_from(_EXTS),
    )
    def test_magic_bytes_beat_any_extension(self, magic, tail, name, ext):
        prefix, expected = magic
        fmt, _, _ = detect_file_format(file_path=name + ext[0], content=prefix + tail)
        self.assertEqual(fmt, expected)

    @given(name=_names, ext=st.sampled_from(_EXTS), upper=st.booleans(),
           inner=st.sampled_from(["", ".xml", ".m3u", ".tar"]))
    def test_the_final_extension_decides_when_content_has_no_magic(
        self, name, ext, upper, inner
    ):
        suffix = inner + ext[0]
        path = name + (suffix.upper() if upper else suffix)
        fmt, _, _ = detect_file_format(file_path=path, content=b"not magic at all")
        self.assertEqual(fmt, ext[1])


class ValidateIconUrlFastProperties(_QuietTaskWarnings):
    @given(url=st.one_of(st.none(), st.text(max_size=300)), max_length=st.integers(1, 256))
    def test_none_exactly_when_the_url_exceeds_max_length(self, url, max_length):
        result = validate_icon_url_fast(url, max_length=max_length)
        if url and len(url) > max_length:
            self.assertIsNone(result)
        else:
            self.assertIs(result, url)

    @given(extra=st.integers(0, 50))
    def test_the_default_bound_is_the_model_field_max_length(self, extra):
        bound = EPGData._meta.get_field("icon_url").max_length
        self.assertEqual(validate_icon_url_fast("h" * bound), "h" * bound)
        self.assertIsNone(validate_icon_url_fast("h" * (bound + 1 + extra)))
