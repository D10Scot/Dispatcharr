"""Property-based tests for EPG ingestion parsing helpers.

Surfaces covered (all consume provider-controlled XMLTV content):

* ``parse_xmltv_time`` — XMLTV timestamp parser. Documents raising on
  malformed input (caught per-element by the bulk parse loops) and promises
  to always return a UTC-aware datetime when it does return.
* ``extract_season_episode_from_description`` / ``extract_season_episode`` —
  description-text season/episode fallback. Promises ``(None, None, desc)``
  when no pattern matches and never to raise on arbitrary text.
* ``_decode_channel_id`` — byte-level channel-id decoder used by the
  programme-index scanner; must match how lxml stores ``EPGData.tvg_id``
  (UTF-8 decode, entity resolution, strip) and never raise on arbitrary bytes.
* ``detect_file_format`` — magic-number/extension sniffer. Promises one of
  five format strings with a consistent ``(is_compressed, extension)`` pair
  and never to raise on arbitrary leading bytes / paths.
* ``parse_text_query`` — boolean/quoted-phrase search parser shared by the
  EPG search API and DVR series rules. Must never raise on arbitrary input
  and must treat the empty query as an empty Q.
* ``sd_poster_cache_bust`` / ``sd_poster_proxy_path`` — pure URL helpers.

Runs without the database or Redis (SimpleTestCase, pure functions).
"""

import re
import string
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.epg.query_utils import parse_text_query
from apps.epg.tasks import _decode_channel_id, detect_file_format, parse_xmltv_time
from apps.epg.utils import (
    extract_season_episode,
    extract_season_episode_from_description,
    sd_poster_cache_bust,
    sd_poster_proxy_path,
)

# CI-deterministic profile — matches the live_proxy property tests.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# parse_xmltv_time
# ---------------------------------------------------------------------------

# Plausible XMLTV timestamps: 'YYYYMMDDHHMMSS' optionally followed by
# ' ±HHMM' (the format the parser actually understands).
xmltv_times = st.builds(
    lambda y, mo, d, h, mi, s, tz: (
        f"{y:04d}{mo:02d}{d:02d}{h:02d}{mi:02d}{s:02d}" + tz
    ),
    y=st.integers(1990, 2100),
    mo=st.integers(1, 12),
    d=st.integers(1, 28),  # stay valid for every month
    h=st.integers(0, 23),
    mi=st.integers(0, 59),
    s=st.integers(0, 59),
    tz=st.one_of(
        st.just(""),
        st.builds(
            lambda sign, th, tm: f" {sign}{th:02d}{tm:02d}",
            sign=st.sampled_from("+-"),
            th=st.integers(0, 14),
            tm=st.integers(0, 59),
        ),
    ),
)

# Arbitrary junk that may appear in a corrupt provider file.
junk_text = st.text(max_size=40) | st.text(
    alphabet=string.digits + "+-: ZT.", max_size=40
)


class XmltvTimeProperties(SimpleTestCase):
    @given(ts=xmltv_times)
    def test_valid_timestamps_parse_to_utc(self, ts):
        """A well-formed XMLTV timestamp always yields an aware UTC datetime."""
        result = parse_xmltv_time(ts)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), timedelta(0))

    @given(ts=xmltv_times)
    def test_roundtrip_without_timezone_assumes_utc(self, ts):
        """Without a zone suffix the wall-clock fields survive unchanged."""
        if " " in ts:
            assume(False)
        result = parse_xmltv_time(ts)
        base = datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(
            tzinfo=dt_timezone.utc
        )
        self.assertEqual(result, base)

    @given(junk=junk_text)
    def test_malformed_input_raises_documented_exception(self, junk):
        """Malformed input raises (ValueError/TypeError) — the documented
        contract the bulk-parse loops rely on — rather than returning garbage
        or crashing with an unexpected exception type."""
        try:
            result = parse_xmltv_time(junk)
        except (ValueError, TypeError, IndexError, OverflowError):
            return
        except Exception as e:  # anything else is a bug
            self.fail(f"unexpected exception type {type(e).__name__}: {e}")
        # If it did not raise, the result must still be a sane UTC datetime.
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), timedelta(0))


# ---------------------------------------------------------------------------
# Season/episode extraction
# ---------------------------------------------------------------------------

class SeasonEpisodeProperties(SimpleTestCase):
    @given(desc=st.text(max_size=200))
    def test_description_fallback_never_raises(self, desc):
        season, episode, cleaned = extract_season_episode_from_description(desc)
        if season is None:
            self.assertIsNone(episode)
            self.assertEqual(cleaned, desc)
        else:
            self.assertIsInstance(season, int)
            self.assertIsInstance(episode, int)
            self.assertGreaterEqual(season, 0)
            self.assertGreaterEqual(episode, 0)
            # The cleaned description is always a stripped suffix of the input.
            self.assertIn(cleaned, desc)

    @given(
        season=st.integers(0, 999),
        episode=st.integers(0, 9999),
        rest=st.text(max_size=80),
    )
    def test_onscreen_prefix_roundtrips(self, season, episode, rest):
        desc = f"S{season}E{episode} {rest}"
        s, e, _ = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))

    @given(
        season=st.integers(0, 999),
        episode=st.integers(0, 99),
        rest=st.text(max_size=80),
    )
    def test_nx_prefix_roundtrips(self, season, episode, rest):
        desc = f"{season}x{episode:02d} {rest}"
        s, e, _ = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))

    @given(
        cp=st.dictionaries(
            keys=st.sampled_from(["season", "episode", "onscreen_episode", "other"]),
            values=st.one_of(
                st.integers(0, 50),
                st.text(alphabet=string.ascii_letters + string.digits, max_size=20),
            ),
            max_size=4,
        ),
        description=st.one_of(st.none(), st.text(max_size=120)),
    )
    def test_extract_season_episode_never_raises_unexpected_types(self, cp, description):
        """Whatever custom_properties holds, extraction either returns or fails
        with the ordinary ValueError/TypeError family — never an exotic error."""
        try:
            extract_season_episode(cp, description)
        except (ValueError, TypeError, AttributeError):
            pass
        except Exception as e:
            self.fail(f"unexpected exception type {type(e).__name__}: {e}")

    @given(
        season=st.integers(0, 100),
        episode=st.integers(0, 100),
    )
    def test_extract_season_episode_prefers_explicit_ints(self, season, episode):
        """Explicit int season/episode in custom_properties win over fallbacks."""
        cp = {"season": season, "episode": episode, "onscreen_episode": "S1E1"}
        s, e = extract_season_episode(cp, "S2E2 something")
        self.assertEqual((s, e), (season, episode))


# ---------------------------------------------------------------------------
# _decode_channel_id
# ---------------------------------------------------------------------------

class DecodeChannelIdProperties(SimpleTestCase):
    @given(raw=st.binary(max_size=200))
    def test_never_raises_and_returns_stripped_text(self, raw):
        result = _decode_channel_id(raw)
        self.assertIsInstance(result, str)
        self.assertEqual(result, result.strip())

    @given(text=st.text(alphabet=string.printable, max_size=60))
    def test_utf8_roundtrip_without_entities(self, text):
        assume("&" not in text)
        assume(text == text.strip())
        self.assertEqual(_decode_channel_id(text.encode("utf-8")), text)

    @given(inner=st.text(alphabet=string.ascii_letters + string.digits, max_size=30))
    def test_numeric_entity_resolution(self, inner):
        assume(inner == inner.strip())
        assume("&" not in inner)
        encoded = f"{inner}&amp;x".encode("utf-8")
        self.assertEqual(_decode_channel_id(encoded), f"{inner}&x")


# ---------------------------------------------------------------------------
# detect_file_format
# ---------------------------------------------------------------------------

class DetectFileFormatProperties(SimpleTestCase):
    @given(content=st.binary(max_size=64))
    def test_arbitrary_content_never_raises(self, content):
        fmt, compressed, ext = detect_file_format(content=content)
        self.assertIn(fmt, ("gzip", "zip", "xz", "xml", "unknown"))
        self.assertIsInstance(compressed, bool)
        self.assertTrue(ext.startswith("."))
        if fmt in ("gzip", "zip", "xz"):
            self.assertTrue(compressed)
        elif fmt in ("xml", "unknown"):
            self.assertFalse(compressed)

    @given(tail=st.binary(max_size=32))
    def test_magic_numbers_win(self, tail):
        self.assertEqual(
            detect_file_format(content=b"\x1f\x8b" + tail)[0], "gzip"
        )
        self.assertEqual(detect_file_format(content=b"PK" + tail)[0], "zip")
        self.assertEqual(
            detect_file_format(content=b"\xfd7zXZ\x00" + tail)[0], "xz"
        )

    @given(name=st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=20))
    def test_extension_fallback(self, name):
        assume("/" not in name and not name.endswith((".gz", ".zip", ".xz", ".xml")))
        for ext, fmt in ((".gz", "gzip"), (".zip", "zip"), (".xz", "xz"), (".xml", "xml")):
            detected, _, _ = detect_file_format(file_path=name + ext)
            self.assertEqual(detected, fmt)


# ---------------------------------------------------------------------------
# parse_text_query
# ---------------------------------------------------------------------------

class ParseTextQueryProperties(SimpleTestCase):
    @given(raw=st.text(max_size=120))
    def test_never_raises_on_arbitrary_input(self, raw):
        q = parse_text_query("title", raw)
        self.assertIsNotNone(q)

    @given(raw=st.text(max_size=120))
    def test_never_raises_in_regex_mode(self, raw):
        # Regex mode passes the raw value to iregex unchanged; building the Q
        # object itself must not raise regardless of pattern validity.
        q = parse_text_query("title", raw, use_regex=True)
        self.assertIsNotNone(q)

    @given(raw=st.text(max_size=120))
    def test_never_raises_in_whole_word_mode(self, raw):
        q = parse_text_query("title", raw, whole_words=True)
        self.assertIsNotNone(q)

    @given(term=st.text(alphabet=string.ascii_letters, min_size=1, max_size=20))
    def test_bare_term_is_icontains(self, term):
        assume(" AND " not in term.upper())
        assume(" OR " not in term.upper())
        assume("(" not in term and '"' not in term)
        q = parse_text_query("title", term)
        self.assertEqual(q.children, [("title__icontains", term)])

    @given(
        a=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10),
        b=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10),
    )
    def test_and_splits_into_two_children(self, a, b):
        assume("(" not in a + b and '"' not in a + b)
        q = parse_text_query("title", f"{a} AND {b}")
        self.assertEqual(q.connector, "AND")
        self.assertEqual(len(q.children), 2)


# ---------------------------------------------------------------------------
# SD poster helpers
# ---------------------------------------------------------------------------

class SdPosterProperties(SimpleTestCase):
    @given(url=st.one_of(st.none(), st.text(max_size=200)))
    def test_cache_bust_is_deterministic_fixed_length(self, url):
        bust = sd_poster_cache_bust(url)
        if not url:
            self.assertEqual(bust, "")
        else:
            self.assertEqual(bust, sd_poster_cache_bust(url))
            self.assertEqual(len(bust), 12)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{12}", bust))

    @given(
        program_id=st.integers(1, 10**12),
        url=st.one_of(st.none(), st.text(max_size=120)),
    )
    def test_proxy_path_shape(self, program_id, url):
        path = sd_poster_proxy_path(program_id, url)
        prefix = f"/api/epg/programs/{program_id}/poster/"
        self.assertTrue(path.startswith(prefix))
        if not url:
            self.assertEqual(path, prefix)
        else:
            self.assertIn("?v=", path)
