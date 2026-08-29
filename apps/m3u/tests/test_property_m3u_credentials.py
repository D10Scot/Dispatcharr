"""Property-based tests for M3U credential/adult-flag helper functions.

Surfaces covered:

* ``utils.parse_is_adult`` — provider adult-flag coercion. The docstring
  promises: True exactly when ``int(value) == 1``; TypeError/ValueError
  inputs (None, "None", empty) are non-adult. The function is total: no
  input may raise.
* ``connection_pool.compute_credential_fingerprint`` — stable SHA-256 for
  grouping accounts sharing an IPTV login. Promises: falsy username or
  password yields ``None``; otherwise a 64-char lowercase hex digest that is
  deterministic, username-case-insensitive, and whitespace-insensitive on
  both inputs (``.strip().lower()`` / ``.strip()`` before hashing).
* ``connection_pool.extract_credentials_from_stream_url`` — parses
  Xtream-style ``/{live|movie|series}/<user>/<pass>/`` URLs via
  ``_XC_URL_CREDENTIALS_RE``. Promises: no match yields ``(None, None)``;
  a matched credential pair is returned verbatim, in order, and each part
  contains no ``/`` (the regex class is ``[^/]+``).
* ``utils.normalize_stream_url`` — VLC ``udp://@`` multicast syntax
  normalisation. Promises: only the ``udp://@`` prefix is rewritten, and
  only its first occurrence; every other input passes through byte-identical
  (including falsy input returned as-is).

All classes are ``SimpleTestCase`` over pure functions — no DB, no Redis.
"""

import hashlib
import re
import string

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
)
from apps.m3u.utils import normalize_stream_url, parse_is_adult

# CI-deterministic profile. Registered/loaded at module import because the
# Django test runner has no pytest-style conftest hook. derandomize=True makes
# runs reproducible; deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


_TEXT_NO_SLASH = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters=("/",)
    ),
    min_size=1,
    max_size=40,
)


class ParseIsAdultProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), st.integers(), st.text(max_size=30)))
    def test_is_total_and_returns_bool(self, value):
        result = parse_is_adult(value)
        self.assertIsInstance(result, bool)

    @given(value=st.one_of(st.none(), st.integers(), st.text(max_size=30)))
    def test_true_iff_int_coercion_equals_one(self, value):
        # The docstring's contract, stated exactly: True when int(value) == 1.
        try:
            expected = int(value) == 1
        except (TypeError, ValueError):
            expected = False
        self.assertIs(parse_is_adult(value), expected)


class CredentialFingerprintProperties(SimpleTestCase):
    @given(username=_TEXT_NO_SLASH, password=_TEXT_NO_SLASH)
    def test_is_deterministic_sha256_hexdigest(self, username, password):
        fp1 = compute_credential_fingerprint(username, password)
        fp2 = compute_credential_fingerprint(username, password)

        self.assertEqual(fp1, fp2)
        self.assertIsNotNone(fp1)
        self.assertRegex(fp1, r"^[0-9a-f]{64}$")
        # And it really is the documented digest of the normalized pair.
        normalized = f"{username.strip().lower()}\0{password.strip()}"
        self.assertEqual(fp1, hashlib.sha256(normalized.encode("utf-8")).hexdigest())

    @given(
        username=_TEXT_NO_SLASH,
        password=_TEXT_NO_SLASH,
        pad=st.text(alphabet=" \t", max_size=4),
    )
    def test_whitespace_and_lower_case_normalization_hold(
        self, username, password, pad
    ):
        """The docstring's stated normalisation: .strip() both sides and
        .lower() the username, so padding and an already-lowered username
        must not change the digest. (Full case-insensitivity for arbitrary
        codepoints is NOT promised by the implementation — .upper()/.lower()
        are not inverse-closed; see the fuzz finding for 'µ'.)"""
        assume(username.strip() and password.strip())
        base = compute_credential_fingerprint(username, password)
        variant = compute_credential_fingerprint(
            pad + username.lower() + pad, pad + password + pad
        )
        self.assertEqual(base, variant)

    @given(
        username=st.one_of(st.none(), st.just(""), st.text(max_size=20)),
        password=st.one_of(st.none(), st.just(""), st.text(max_size=20)),
    )
    def test_falsy_either_side_yields_none(self, username, password):
        assume(not username or not password)
        self.assertIsNone(compute_credential_fingerprint(username, password))


class ExtractCredentialsProperties(SimpleTestCase):
    @given(
        kind=st.sampled_from(("live", "movie", "series")),
        username=_TEXT_NO_SLASH,
        password=_TEXT_NO_SLASH,
        stream_id=st.text(
            alphabet=string.ascii_letters + string.digits + "._-", min_size=1,
            max_size=20,
        ),
    )
    def test_extracts_verbatim_from_canonical_url(
        self, kind, username, password, stream_id
    ):
        url = f"http://provider.example:8080/{kind}/{username}/{password}/{stream_id}.ts"
        self.assertEqual(
            extract_credentials_from_stream_url(url), (username, password)
        )

    @given(kind=st.sampled_from(("LIVE", "Movie", "SeRiEs")))
    def test_kind_keyword_is_case_insensitive(self, kind):
        url = f"http://h/{kind}/alice/s3cret/1.ts"
        self.assertEqual(extract_credentials_from_stream_url(url), ("alice", "s3cret"))

    @given(url=st.text(max_size=60))
    def test_arbitrary_text_never_raises_and_obeys_regex_contract(self, url):
        user, password = extract_credentials_from_stream_url(url)
        if user is None:
            self.assertIsNone(password)
        else:
            self.assertIsNotNone(password)
            self.assertNotIn("/", user)
            self.assertNotIn("/", password)
            # The pair really occurs in the URL, user before password.
            self.assertLess(url.index(user), url.index(password))

    @given(url=st.one_of(st.none(), st.just("")))
    def test_falsy_url_yields_none_pair(self, url):
        self.assertEqual(extract_credentials_from_stream_url(url), (None, None))


class NormalizeStreamUrlProperties(SimpleTestCase):
    @given(url=st.text(max_size=80))
    def test_non_udp_at_urls_pass_through_identically(self, url):
        assume(not url.startswith("udp://@"))
        self.assertIs(normalize_stream_url(url), url)

    @given(rest=st.text(max_size=60))
    def test_udp_at_prefix_is_stripped_once(self, rest):
        url = "udp://@" + rest
        normalized = normalize_stream_url(url)
        self.assertEqual(normalized, "udp://" + rest)
        # Only the prefix is touched: the remainder is byte-identical.
        self.assertTrue(url.endswith(normalized[len("udp://"):]))

    @given(url=st.one_of(st.none(), st.just("")))
    def test_falsy_url_returned_as_is(self, url):
        self.assertEqual(normalize_stream_url(url), url)


class ParseExtinfAttrKeyCaseProperties(SimpleTestCase):
    """parse_extinf_line lowercases attribute keys; verify lookup stability."""

    @given(
        key=st.text(
            alphabet=string.ascii_letters + string.digits + "-_",
            min_size=1,
            max_size=12,
        ),
        value=st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters=("\"", "'", "\n", "\r"),
            ),
            max_size=20,
        ),
    )
    def test_attribute_keys_are_lowercased(self, key, value):
        from apps.m3u.tasks import parse_extinf_line

        line = f'#EXTINF:-1 {key}="{value}",Name'
        parsed = parse_extinf_line(line)
        self.assertIsNotNone(parsed)
        for attr_key in parsed["attributes"]:
            self.assertEqual(attr_key, attr_key.lower())
