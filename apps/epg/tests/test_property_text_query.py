"""Property-based tests for ``parse_text_query`` (apps/epg/query_utils.py:35).

The shared search-expression parser behind the EPG search API
(apps/epg/api_views.py:262, :268), the DVR series-rule evaluator
(apps/channels/tasks.py:591, :598) and the recordings search
(apps/channels/api_views.py:4219, :4225). Its input is whatever a user types.

Two seed behaviours are deliberately kept out of these properties and are
reported in plan I's findings section rather than pinned (the first is
finding F-1; the second is noted there without a number):

* Text whose ``str.upper()`` is longer than itself (``\\u00df``, ``\\u0149``,
  ``\\ufb03``, ...) next to an operator word raises ``IndexError``: the
  operator scan finds positions in ``remaining.upper()`` and slices the
  original string with them. ``parse_text_query("title", "\\u00df a AND b")``
  raises. The no-raise properties therefore draw only length-preserving text.
* The docstring says regex mode treats the whole value as one regex, but the
  parser still splits it on parentheses and AND/OR (``(foo|bar) baz`` becomes
  two ``iregex`` lookups). Regex mode is only held to "never raises" here.

Closes the parse_text_query part of #202 (and duplicates #274, #158, #74).
"""

import re
import string

from django.db.models import Q
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.epg.query_utils import parse_text_query

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def _upper_preserves_length(s):
    return len(s.upper()) == len(s)


# Arbitrary user text plus operator-dense text, restricted to characters whose
# upper case has the same length (see the module docstring).
_OPS = st.sampled_from([" AND ", " OR ", " and ", " Or ", "(", ")", '"', " ", "x", "news"])
query_text = st.one_of(
    st.text(max_size=80),
    st.lists(st.one_of(_OPS, st.text(max_size=6)), max_size=20).map("".join),
).filter(_upper_preserves_length)

_WORD = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=12).filter(
    lambda w: w not in ("and", "or")
)
_PHRASE = st.lists(
    st.sampled_from(["AND", "OR", "and", "(", ")", "news", "tv", "x"]),
    min_size=1, max_size=6,
).map(" ".join)


def _leaves(q):
    return q.children


class ParseTextQueryProperties(SimpleTestCase):
    @given(raw=query_text, use_regex=st.booleans(), whole_words=st.booleans())
    def test_any_length_preserving_text_builds_a_q_without_raising(
        self, raw, use_regex, whole_words
    ):
        self.assertIsInstance(
            parse_text_query("title", raw, use_regex=use_regex, whole_words=whole_words),
            Q,
        )

    @given(
        term=st.text(max_size=30).filter(
            lambda t: t.strip() and not re.search(r"[()\"]| (and|or) ", t, re.I)
        )
    )
    def test_a_bare_term_is_one_icontains_on_its_stripped_text(self, term):
        q = parse_text_query("title", term)
        self.assertEqual(q.children, [("title__icontains", term.strip())])

    @given(a=_WORD, b=_WORD, op=st.sampled_from(["AND", "and", "And", "OR", "or"]))
    def test_a_binary_operator_joins_two_icontains_leaves(self, a, b, op):
        q = parse_text_query("title", f"{a} {op} {b}")
        self.assertEqual(q.connector, "AND" if op.upper() == "AND" else "OR")
        self.assertEqual(
            _leaves(q), [("title__icontains", a), ("title__icontains", b)]
        )

    @given(p1=_PHRASE, p2=_PHRASE)
    def test_double_quoted_phrases_stay_atomic_whatever_they_contain(self, p1, p2):
        q = parse_text_query("title", f'"{p1}" AND "{p2}"')
        self.assertEqual(q.connector, "AND")
        self.assertEqual(
            _leaves(q), [("title__icontains", p1), ("title__icontains", p2)]
        )

    @given(word=st.text(alphabet=string.ascii_letters, min_size=1, max_size=12))
    def test_whole_word_mode_matches_the_word_only_at_word_boundaries(self, word):
        q = parse_text_query("title", word, whole_words=True)
        ((lookup, pattern),) = q.children
        self.assertEqual(lookup, "title__iregex")
        # PostgreSQL's \y is Python's \b; check the pattern's meaning, not its text.
        py = re.compile(pattern.replace(r"\y", r"\b"), re.IGNORECASE)
        self.assertTrue(py.search(f"foo {word} bar"))
        self.assertTrue(py.search(f"{word.upper()}."))
        self.assertIsNone(py.search(f"foo{word}bar"))
