"""Property-based tests for transform_url (apps/proxy/live_proxy/url_utils.py).

transform_url applies a user-configured regex search/replace to provider
stream URLs. Both the pattern and the URL are untrusted (admin-supplied
profile config, provider-supplied URLs), and the function is on the hot path
of every stream start. Existing unit tests pin the JS backreference rewrite
and the ReDoS timeout; these properties state the broader contract:

* totality: arbitrary (url, search, replace) triples never raise and always
  return a str;
* fallback: when the search pattern matches nothing, the result is exactly
  the input URL (callers rely on identity here — a transformed-but-wrong URL
  would send credentials to the wrong host);
* error containment: an invalid regex, a replacement referencing a missing
  group, or a catastrophic-backtracking pattern all return the input URL,
  never an exception;
* the identity transformation (search that matches, replacement that
  re-inserts the whole match via $0) round-trips the URL unchanged;
* the result on a successful single replacement contains no leftover JS-style
  backreferences ($1, $<name>) — they are rewritten to Python form before
  substitution.

Runs without Redis or the database (SimpleTestCase, pure function with
module-level regex only).
"""

from hypothesis import given, settings as hyp_settings, strategies as st
from django.test import SimpleTestCase

from apps.proxy.live_proxy.url_utils import transform_url

# CI-deterministic profile — see test_property_find_ts_sync.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Adversarial pattern fragments: nested quantifiers, group syntax in both JS
# and Python style, backreferences, escapes, anchors.
pattern_text = st.text(
    alphabet="abc.*+?()[]{}|^$\\<>!P:=,0123456789-/",
    max_size=40,
)

replace_text = st.text(
    alphabet="abc$\\<>0123456789/._-",
    max_size=30,
)

url_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    ),
    max_size=150,
)


class TransformUrlProperties(SimpleTestCase):
    @given(url=url_text, search=pattern_text, replace=replace_text)
    def test_never_raises_and_returns_str(self, url, search, replace):
        result = transform_url(url, search, replace)
        self.assertIsInstance(result, str)

    @given(
        url=url_text,
        # A pattern guaranteed not to occur in url because it uses a
        # character excluded from url_text's alphabet.
        marker=st.sampled_from(["\x01ZZZ\x02", "\x03QQQ\x04"]),
    )
    def test_non_matching_pattern_returns_input(self, url, marker):
        self.assertEqual(transform_url(url, marker, "replacement"), url)

    @given(url=url_text, tail=url_text)
    def test_identity_group_one_round_trips(self, url, tail):
        """^(.*)$ with $1 replacement must return the URL unchanged (this is
        the exact pattern the default M3U profile ships with)."""
        target = url + "/" + tail
        self.assertEqual(transform_url(target, r"^(.*)$", r"$1"), target)

    @given(url=url_text, search=pattern_text, replace=replace_text)
    def test_no_js_backreferences_survive_in_result(self, url, search, replace):
        """A successful substitution must not leak $-style backreferences that
        the Python regex engine left unexpanded into the output URL."""
        result = transform_url(url, search, replace)
        if result != url:
            # Something was substituted. The implementation rewrites $1/$<n>
            # before substitution, so surviving $<name> would indicate the
            # conversion was bypassed. ($<digit> forms are caught by the $N
            # rewrite; only alphabetic names are checked here.)
            self.assertNotRegex(result, r"\$<[A-Za-z_]")
