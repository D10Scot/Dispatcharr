"""Property-based tests for EPG programme-metadata extraction and SD helpers.

Surfaces covered (provider-controlled input arrives as XMLTV bytes or as
Schedules Direct JSON):

* ``extract_custom_properties`` — maps a parsed ``<programme>`` element to the
  ``custom_properties`` JSON blob. Runs inside the hot bulk-parse loop over
  every programme of every provider file, so it must never raise on any
  well-formed XML shape, and must keep its typed promises (``season`` /
  ``episode`` are positive ints when present — the XMLTV ``xmltv_ns`` format
  is zero-based and the extractor adds 1; ``length`` only appears when its
  text parses as an int).
* ``_programme_to_dict`` — the current-programme lookup's serializer. Promises
  a fixed five-key dict with string fields regardless of which child elements
  the provider included.
* ``_parse_programme_element`` — the DOCTYPE-injecting parser behind the
  current-programme path. Predefined and numeric entities resolve the way
  ``html.unescape`` says they should; unresolvable bytes only ever raise the
  documented ``etree.XMLSyntaxError`` (both call sites catch exactly that).
* ``_CHANNEL_ATTR_RE`` — the byte-level ``channel=`` extractor shared by the
  index builder and the current-programme scanner. Must never raise, and its
  capture groups must obey the single/double-quote split the pattern declares.
* ``sd_auth_lockout_seconds_for_code`` — cooldown table for /token failures.
  Pure mapping from SD error code to one of the three documented cooldowns,
  with the account-locked and soft-code orderings (a mis-ordered check would
  either hammer SD or lock users out for 24h on a transient failure).
* ``sd_credential_fingerprint`` — stable hash pairing a persisted lockout /
  cached token with the credentials that produced it. Promises determinism
  and None-vs-empty-string normalization (a lockout must clear exactly when
  the user changes username or password — never silently keep matching, never
  spuriously stop matching).
* ``validate_icon_url_fast`` — length guard for provider-supplied icon URLs.
  Promises ``None`` iff the URL exceeds the model field's max_length.

Runs without the database or Redis (SimpleTestCase, pure functions).
"""

import html
import string

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg.sd_utils import (
    SD_AUTH_LOCKOUT_SECONDS,
    SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK,
    SD_AUTH_LOCKOUT_SECONDS_SOFT,
    SD_AUTH_SOFT_CODES,
    SD_CODE_ACCOUNT_LOCKED,
    sd_auth_failure_message,
    sd_auth_lockout_seconds_for_code,
    sd_credential_fingerprint,
    sd_token_response_code,
)
from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _parse_programme_element,
    _programme_to_dict,
    extract_custom_properties,
    validate_icon_url_fast,
)

from datetime import datetime
from datetime import timezone as dt_timezone

# CI-deterministic profile — matches the other property-test modules.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# XML name characters — conservative so generated fragments stay well-formed.
_NAME_ALPHABET = string.ascii_lowercase

# Text that can carry entities / markup-ish bytes but no raw '<' or '&'.
_TEXT_ALPHABET = string.ascii_letters + string.digits + " \t-_.:,;!?()[]#'\"/\\"

xml_text = st.text(alphabet=_TEXT_ALPHABET, max_size=60)

# Element tag names drawn from the ones extract_custom_properties actually
# reads, plus arbitrary names it must ignore.
_TAG_NAMES = st.sampled_from(
    [
        "category",
        "keyword",
        "episode-num",
        "rating",
        "star-rating",
        "credits",
        "date",
        "country",
        "language",
        "orig-language",
        "length",
        "video",
        "audio",
        "subtitles",
        "review",
        "image",
        "icon",
        "previously-shown",
        "premiere",
        "new",
        "live",
        "last-chance",
        "title",
        "desc",
        "sub-title",
        "bogus-element",
    ]
)


def _child_xml(tag, text):
    return f"<{tag}>{html.escape(text, quote=True)}</{tag}>"


programme_children = st.lists(
    st.tuples(_TAG_NAMES, xml_text), max_size=12
).map(lambda pairs: "".join(_child_xml(t, x) for t, x in pairs))


# ---------------------------------------------------------------------------
# extract_custom_properties
# ---------------------------------------------------------------------------

class ExtractCustomPropertiesProperties(SimpleTestCase):
    @given(children=programme_children)
    def test_never_raises_on_wellformed_elements(self, children):
        elem = etree.fromstring(f"<programme>{children}</programme>")
        props = extract_custom_properties(elem)
        self.assertIsInstance(props, dict)

    @given(children=programme_children)
    def test_typed_promises_hold(self, children):
        elem = etree.fromstring(f"<programme>{children}</programme>")
        props = extract_custom_properties(elem)
        # xmltv_ns is zero-based and the extractor adds 1, so any stored
        # season/episode is a positive int — never zero, never negative.
        for key in ("season", "episode"):
            if key in props:
                self.assertIsInstance(props[key], int)
                self.assertGreaterEqual(props[key], 1)
        if "length" in props:
            self.assertIsInstance(props["length"]["value"], int)
            self.assertIsInstance(props["length"]["units"], str)
        for key in ("categories", "keywords"):
            if key in props:
                # Stripped and non-empty — the comprehensions filter blanks.
                self.assertTrue(props[key])
                for item in props[key]:
                    self.assertTrue(item)
                    self.assertEqual(item, item.strip())

    @given(
        season_zero_based=st.integers(0, 200),
        episode_zero_based=st.integers(0, 2000),
    )
    def test_xmltv_ns_is_converted_to_one_based(self, season_zero_based, episode_zero_based):
        elem = etree.fromstring(
            '<programme><episode-num system="xmltv_ns">'
            f"{season_zero_based}.{episode_zero_based}."
            "</episode-num></programme>"
        )
        props = extract_custom_properties(elem)
        self.assertEqual(props["season"], season_zero_based + 1)
        self.assertEqual(props["episode"], episode_zero_based + 1)

    @given(text=xml_text)
    def test_length_only_recorded_when_int_parseable(self, text):
        elem = etree.fromstring(
            f"<programme><length>{html.escape(text)}</length></programme>"
        )
        props = extract_custom_properties(elem)
        stripped = text.strip()
        try:
            expected = int(stripped)
        except ValueError:
            self.assertNotIn("length", props)
        else:
            self.assertEqual(props["length"]["value"], expected)


# ---------------------------------------------------------------------------
# _programme_to_dict
# ---------------------------------------------------------------------------

class ProgrammeToDictProperties(SimpleTestCase):
    @given(children=programme_children)
    def test_fixed_shape_and_string_fields(self, children):
        elem = etree.fromstring(f"<programme>{children}</programme>")
        now = datetime.now(dt_timezone.utc)
        result = _programme_to_dict(elem, now, now)
        self.assertEqual(
            set(result),
            {"title", "description", "sub_title", "start_time", "end_time"},
        )
        for key in ("title", "description", "sub_title"):
            self.assertIsInstance(result[key], str)
        # Timestamps are passed through as ISO strings of the given datetimes.
        self.assertEqual(result["start_time"], now.isoformat())
        self.assertEqual(result["end_time"], now.isoformat())


# ---------------------------------------------------------------------------
# _parse_programme_element
# ---------------------------------------------------------------------------

class ParseProgrammeElementProperties(SimpleTestCase):
    @given(text=xml_text)
    def test_predefined_and_numeric_entities_resolve_like_html(self, text):
        payload = html.escape(text, quote=False)
        elem = _parse_programme_element(
            f"<programme><title>{payload}</title></programme>".encode("utf-8")
        )
        self.assertEqual(elem.tag, "programme")
        self.assertEqual(elem.findtext("title"), text)

    @given(raw=st.binary(max_size=120))
    def test_parse_or_documented_raise_only(self, raw):
        """Byte soup either parses or raises XMLSyntaxError — nothing else.

        Both call sites (_read_programs_at_offsets, _scan_from_offset_for_tvg_id)
        catch exactly ``etree.XMLSyntaxError``; any other exception type would
        escape the current-programme lookup as a 500.
        """
        try:
            elem = _parse_programme_element(raw)
        except etree.XMLSyntaxError:
            return
        # Parsed: the injected DOCTYPE guarantees a single root element.
        self.assertIsNotNone(elem.tag)


# ---------------------------------------------------------------------------
# _CHANNEL_ATTR_RE
# ---------------------------------------------------------------------------

class ChannelAttrRegexProperties(SimpleTestCase):
    @given(buf=st.binary(max_size=200))
    def test_never_raises_on_byte_soup(self, buf):
        _CHANNEL_ATTR_RE.search(buf)

    @given(
        value=st.text(
            alphabet=string.ascii_letters + string.digits + " \t-_.:/", min_size=1, max_size=40
        )
    )
    def test_roundtrip_double_quoted(self, value):
        assume('"' not in value)
        buf = f'<programme channel="{value}">'.encode()
        m = _CHANNEL_ATTR_RE.search(buf)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), value.encode())
        self.assertIsNone(m.group(2))

    @given(
        value=st.text(
            alphabet=string.ascii_letters + string.digits + " \t-_.:/", min_size=1, max_size=40
        )
    )
    def test_roundtrip_single_quoted(self, value):
        assume("'" not in value)
        buf = f"<programme channel='{value}'>".encode()
        m = _CHANNEL_ATTR_RE.search(buf)
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), value.encode())

    def test_empty_value_never_matches(self):
        # The pattern uses +, so channel="" must not capture an empty id —
        # an empty tvg_id would corrupt the programme index.
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b'<programme channel="">'))
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b"<programme channel=''>"))

    @given(buf=st.binary(max_size=200))
    def test_capture_groups_are_mutually_exclusive(self, buf):
        m = _CHANNEL_ATTR_RE.search(buf)
        if m is None:
            return
        g1, g2 = m.group(1), m.group(2)
        # Exactly one branch of the alternation participated.
        self.assertEqual((g1 is not None) + (g2 is not None), 1)
        # A double-quoted capture never contains a double quote, and the
        # single-quoted capture never contains a single quote (that's what
        # keeps the scanner aligned with the XML tokenizer).
        if g1 is not None:
            self.assertNotIn(b'"', g1)
        else:
            self.assertNotIn(b"'", g2)


# ---------------------------------------------------------------------------
# sd_auth_lockout_seconds_for_code
# ---------------------------------------------------------------------------

class SdAuthLockoutProperties(SimpleTestCase):
    @given(code=st.integers(-10, 10000) | st.none() | st.text(max_size=10))
    def test_result_is_always_a_documented_cooldown(self, code):
        seconds = sd_auth_lockout_seconds_for_code(code)
        self.assertIn(
            seconds,
            (
                SD_AUTH_LOCKOUT_SECONDS,
                SD_AUTH_LOCKOUT_SECONDS_SOFT,
                SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK,
            ),
        )

    def test_ordering_account_locked_is_shortest(self):
        # A locked account gets the shortest cooldown (the user must fix
        # credentials anyway); soft (transient) failures get the middle one,
        # and everything else the 24h default. A mis-ordered check would
        # either hammer SD or park users for a day on a blip.
        self.assertLess(
            sd_auth_lockout_seconds_for_code(SD_CODE_ACCOUNT_LOCKED),
            sd_auth_lockout_seconds_for_code(next(iter(SD_AUTH_SOFT_CODES))),
        )
        self.assertLess(
            sd_auth_lockout_seconds_for_code(next(iter(SD_AUTH_SOFT_CODES))),
            sd_auth_lockout_seconds_for_code(-1),
        )

    @given(code=st.sampled_from(sorted(SD_AUTH_SOFT_CODES)))
    def test_soft_codes_get_soft_cooldown(self, code):
        self.assertEqual(
            sd_auth_lockout_seconds_for_code(code), SD_AUTH_LOCKOUT_SECONDS_SOFT
        )


# ---------------------------------------------------------------------------
# sd_credential_fingerprint
# ---------------------------------------------------------------------------

class SdCredentialFingerprintProperties(SimpleTestCase):
    @given(
        username=st.one_of(st.none(), st.text(max_size=80)),
        password=st.one_of(st.none(), st.text(max_size=80)),
    )
    def test_deterministic_and_hex(self, username, password):
        fp1 = sd_credential_fingerprint(username, password)
        fp2 = sd_credential_fingerprint(username, password)
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)
        self.assertTrue(all(c in string.hexdigits for c in fp1))

    @given(
        username=st.text(alphabet=string.printable, max_size=40),
        password=st.text(alphabet=string.printable, max_size=40),
    )
    def test_changing_either_credential_changes_fingerprint(self, username, password):
        base = sd_credential_fingerprint(username, password)
        # Any actual edit to username or password must bust the fingerprint —
        # that's the mechanism that auto-clears lockouts on credential update.
        self.assertNotEqual(base, sd_credential_fingerprint(username + "x", password))
        self.assertNotEqual(base, sd_credential_fingerprint(username, password + "x"))

    @given(password=st.one_of(st.none(), st.text(max_size=40)))
    def test_none_and_empty_normalize_together(self, password):
        # None and "" are the same credential as far as SD is concerned;
        # the lockout must not distinguish them.
        self.assertEqual(
            sd_credential_fingerprint(None, password),
            sd_credential_fingerprint("", password),
        )
        self.assertEqual(
            sd_credential_fingerprint(password, None),
            sd_credential_fingerprint(password, ""),
        )


# ---------------------------------------------------------------------------
# sd_token_response_code / sd_auth_failure_message
# ---------------------------------------------------------------------------

class SdTokenResponseCodeProperties(SimpleTestCase):
    @given(
        data=st.one_of(
            st.none(),
            st.binary(max_size=40),
            st.text(max_size=40),
            st.integers(),
            st.dictionaries(
                st.text(max_size=12),
                st.one_of(st.integers(-10, 10000), st.text(max_size=12), st.none()),
                max_size=6,
            ),
        )
    )
    def test_always_returns_an_int(self, data):
        # The /token polling loop branches on this value; a non-int leak
        # would crash it, so the function promises an int for any JSON shape.
        result = sd_token_response_code(data)
        self.assertIsInstance(result, int)

    @given(code=st.integers(-10, 10000))
    def test_int_code_roundtrips(self, code):
        self.assertEqual(sd_token_response_code({"code": code}), code)

    @given(code=st.one_of(st.text(max_size=20), st.none(), st.lists(st.integers(), max_size=3)))
    def test_non_int_code_becomes_zero(self, code):
        # bool is a subclass of int and accepted by isinstance — exclude it.
        assume(not isinstance(code, bool))
        self.assertEqual(sd_token_response_code({"code": code}), 0)


class SdAuthFailureMessageProperties(SimpleTestCase):
    @given(
        code=st.one_of(st.integers(-10, 10000), st.none(), st.text(max_size=12)),
        sd_message=st.one_of(st.none(), st.text(max_size=60)),
    )
    def test_always_returns_nonempty_str(self, code, sd_message):
        msg = sd_auth_failure_message(code, sd_message)
        self.assertIsInstance(msg, str)
        self.assertTrue(msg)

    @given(sd_message=st.text(alphabet=string.printable, min_size=1, max_size=60))
    def test_unknown_code_echoes_sd_message(self, sd_message):
        # Codes outside the known table fall through to the generic message,
        # which must carry the provider's own text so the user can act on it.
        assume("\n" not in sd_message and "\r" not in sd_message)
        msg = sd_auth_failure_message(9999, sd_message)
        self.assertIn(sd_message, msg)
        self.assertIn("9999", msg)


# ---------------------------------------------------------------------------
# validate_icon_url_fast
# ---------------------------------------------------------------------------

class ValidateIconUrlProperties(SimpleTestCase):
    @given(url=st.text(max_size=1200), max_length=st.integers(1, 1024))
    def test_none_iff_too_long(self, url, max_length):
        result = validate_icon_url_fast(url, max_length=max_length)
        if url and len(url) > max_length:
            self.assertIsNone(result)
        else:
            self.assertEqual(result, url)

    @given(max_length=st.integers(1, 1024))
    def test_falsy_input_passes_through(self, max_length):
        self.assertEqual(validate_icon_url_fast("", max_length=max_length), "")
        self.assertIsNone(validate_icon_url_fast(None, max_length=max_length))
