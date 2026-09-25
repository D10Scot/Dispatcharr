"""Property tests for the credential helpers behind the shared connection pool
(issues #218, #69; seam #68).

Surfaces, with their line at seed a54b09a9:

- ``compute_credential_fingerprint`` (``apps/m3u/connection_pool.py:49``). It
  groups accounts that share one IPTV login so they share one cap. The
  username is case-insensitive and the password is not.
- ``extract_credentials_from_stream_url`` (``apps/m3u/connection_pool.py:57``).
  It parses ``/live|movie|series/<user>/<pass>/`` out of an Xtream stream URL.

The #68 seam: the seed normalises the username with ``.lower()``, which is not
a caseless match. ``'µ'`` (U+00B5) upper-cases to U+039C, which lower-cases to
U+03BC. So the two spellings of one login fingerprint differently and escape
the shared cap. C-5 switches to ``.casefold()``.
"""

import string

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

credentials = st.text(max_size=40)
# A username that Unicode's default caseless matching treats as the same login
# as its upper-case spelling. This excludes the few code points where upper()
# is not caseless-equivalent (e.g. dotless 'ı' upper-cases to 'I', which
# folds to 'i'), where no case-insensitive grouping is correct. The filter
# restricts the domain only; the assertion is on the fingerprint.
caseless_usernames = st.text(min_size=1, max_size=30).filter(
    lambda u: u.strip() and u.upper().casefold() == u.casefold()
)
passwords = st.text(min_size=1, max_size=30).filter(lambda p: p.strip())


class CredentialFingerprintProperties(SimpleTestCase):
    @given(username=st.none() | credentials, password=st.none() | credentials)
    def test_fingerprint_is_deterministic_hex_or_none_exactly_when_a_credential_is_blank(
        self, username, password
    ):
        fp = compute_credential_fingerprint(username, password)
        self.assertEqual(fp, compute_credential_fingerprint(username, password))
        if not username or not password:
            self.assertIsNone(fp)
        else:
            self.assertRegex(fp, r"^[0-9a-f]{64}$")

    @given(
        username=caseless_usernames,
        password=passwords,
        spelling=st.sampled_from((str.upper, str.lower, str.swapcase)),
        pad=st.sampled_from(("", " ", "  \t")),
    )
    # #68 (and #69's shrink, 'μ'): the micro sign and its upper-case spelling
    # fingerprinted differently under .lower().
    @example(username="µ", password="0", spelling=str.upper, pad="")
    def test_case_and_surrounding_whitespace_variants_of_a_username_share_a_fingerprint(
        self, username, password, spelling, pad
    ):
        self.assertEqual(
            compute_credential_fingerprint(username, password),
            compute_credential_fingerprint(pad + spelling(username) + pad, password),
        )

    @given(
        username=st.text(alphabet=string.ascii_letters, min_size=1, max_size=10),
        password=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=20).filter(
            lambda p: p.swapcase() != p
        ),
    )
    def test_a_password_differing_only_in_case_is_a_different_login(self, username, password):
        self.assertNotEqual(
            compute_credential_fingerprint(username, password),
            compute_credential_fingerprint(username, password.swapcase()),
        )


segment = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="/"),
    min_size=1,
    max_size=20,
)


class ExtractCredentialsProperties(SimpleTestCase):
    @given(url=st.text(max_size=200))
    def test_extraction_is_total_and_both_or_neither(self, url):
        user, password = extract_credentials_from_stream_url(url)
        if user is None:
            self.assertIsNone(password)
        else:
            self.assertNotIn("/", user)
            self.assertNotIn("/", password)
            self.assertTrue(user and password)

    @given(
        user=segment,
        password=segment,
        kind=st.sampled_from(("live", "movie", "series", "LIVE", "Movie")),
        host=st.sampled_from(("http://h", "https://h.example:8080", "http://h/sub")),
        tail=st.sampled_from(("1.ts", "99999.m3u8", "7.mkv")),
    )
    def test_xtream_url_round_trips_user_and_password(self, user, password, kind, host, tail):
        url = f"{host}/{kind}/{user}/{password}/{tail}"
        self.assertEqual(extract_credentials_from_stream_url(url), (user, password))

    @given(path=st.text(alphabet=string.ascii_letters + "/.", max_size=40))
    def test_a_url_without_a_kind_segment_yields_no_credentials(self, path):
        url = "http://h/" + path.replace("live", "").replace("movie", "").replace("series", "")
        self.assertEqual(extract_credentials_from_stream_url(url), (None, None))
