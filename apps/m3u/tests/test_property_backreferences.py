r"""Property tests for ``convert_js_numbered_backreferences`` (issues #218, #69; seam #171).

Surface at seed a54b09a9: ``apps/m3u/utils.py:13``. The helper turns a
JavaScript-style replacement template (``$1``) into a Python ``regex``
template, and the auto-sync rename feeds the result to ``regex.sub``
(``apps/m3u/tasks.py:2608``). These properties exercise it the way the rename
does -- ``regex.sub(pattern, convert(template), target)`` -- because the
defect (#171) is what the converted template *does*, not what it looks like.

C-4 merged with ``$0`` literal, so neither property below hedges on that
reading:

1. The output contains no character that is in neither the target nor the
   template. Before C-4, ``$0`` became ``\0`` (a NUL byte) and ``$01`` became
   ``\01`` (U+0001). Generated templates exclude the backslash: the helper
   hands a backslash straight to Python's replacement-template parser, which
   JavaScript never does, so a template containing one reopens exactly this
   symptom (#452). The alphabet widens to include the backslash once #452 is
   ruled.
2. For templates whose tokens are ``$N`` or ``$0N`` with 1 <= N <= the group
   count, and whose next literal character is not a digit, the output equals
   a hand-written model of JavaScript's ``String.prototype.replace`` with a
   global regex (ECMA-262 GetSubstitution): ``$N`` is group N's text, or ""
   when the group did not participate. The model uses ``regex.finditer`` only
   to find matches; it never calls the helper under test.

C-4's adopted rule is ``\$(0[1-9]|[1-9]\d?)`` -> ``\g<N>``, JavaScript's own
``$n``/``$nn`` grammar: at most two digits after ``$``, and a leading zero only
as ``$0n``. ``test_multi_digit_tokens_read_exactly_as_javascript_does`` pins
the multi-digit cases against outputs recorded from Node 22's
``String.prototype.replace`` (the oracle is a table of constants, not the
code under test).

Out of scope, per C-4 review finding F2, and not asserted by either property
above (property 2's literal runs exclude ``$``, so they cannot drift into
covering these by accident): ``$$`` stays ``$$``; ``$$1`` reads as a literal
``$`` followed by group 1 (``$a``); the whole-match, pre-match and post-match
tokens (``$&``, the backtick token, ``$'``) stay literal; and a reference to
a group that does not exist raises rather than falling back to a literal
token. One divergence C-4 records as pre-existing and this plan does not
change: JavaScript's own fallback when group ``nn`` does not exist (``$10``
with two groups reads ``$1`` then a literal ``0``) -- the helper refuses the
whole template instead.
"""

import regex
from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.utils import convert_js_numbered_backreferences

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# (pattern, group count). Fixed, simple patterns on which JavaScript and the
# ``regex`` module agree about what matches; the property is about the
# replacement template, not the regex engine.
PATTERNS = [
    (r"(a)", 1),
    (r"(a)(b)", 2),
    (r"(.)(.)?", 2),
    (r"(.*)$", 1),
    (r"(h)/(u)", 2),
    (r"([a-z]+)-(\d+)?", 2),
]
targets = st.text(alphabet="abhu/-0123456789xy", max_size=24)
# Templates as the operator types them: literals, digits and ``$``, but no
# backslash. The helper hands a backslash straight to Python's replacement-
# template parser, which JavaScript never does, so a template containing one
# reopens #171's corrupted-output symptom (#452); the alphabet widens once
# #452 is ruled.
templates = st.text(alphabet="ab/-[]$0123456789x", max_size=16)


def _apply(pattern, template, target):
    """The rename's call shape. ``None`` means the template was rejected."""
    try:
        return regex.sub(pattern, convert_js_numbered_backreferences(template), target)
    except (regex.error, IndexError):
        return None  # an invalid group number is refused, not corrupted


@st.composite
def js_templates(draw, group_count):
    """A template of literal runs and ``$N``/``$0N`` tokens, N in 1..group_count.

    A literal run following a token never starts with a digit: JavaScript
    would read that digit as part of a two-digit group number, a divergence
    C-4 documents and does not change.
    """
    pieces = []
    for _ in range(draw(st.integers(min_value=0, max_value=5))):
        if draw(st.booleans()):
            n = draw(st.integers(min_value=1, max_value=group_count))
            zero = draw(st.sampled_from(("", "0")))
            pieces.append(("group", n, f"${zero}{n}"))
        else:
            first = draw(st.sampled_from("ab/-[]x"))
            rest = draw(st.text(alphabet="ab/-[]x0123456789", max_size=4))
            pieces.append(("literal", None, first + rest))
    return pieces


def _javascript_replace(pattern, pieces, target):
    out = []
    last = 0
    for m in regex.finditer(pattern, target):
        out.append(target[last:m.start()])
        for kind, n, text in pieces:
            out.append((m.group(n) or "") if kind == "group" else text)
        last = m.end()
    out.append(target[last:])
    return "".join(out)


# One near-guaranteed matching seed per PATTERNS entry (review finding 3):
# property 1's free-form ``templates``/``targets`` draw a live ``$N``
# substitution on only about 1 in 200 calls, because a random 16-character
# template rarely happens to contain a syntactically valid token, and a
# random 24-character target rarely happens to match the pattern at all. Half
# of property 1's draws instead build a template from ``js_templates`` (which
# always emits a well-formed token whenever it emits a "group" piece) against
# a target seeded with a substring the pattern is virtually certain to match,
# so the property actually exercises a live substitution rather than only its
# two ``@example`` rows.
_MATCHING_SEED = {
    r"(a)": "a",
    r"(a)(b)": "ab",
    r"(.)(.)?": "ab",  # matches almost any non-empty target; seed is just clarity
    r"(.*)$": "",  # matches every target, including empty
    r"(h)/(u)": "h/u",
    r"([a-z]+)-(\d+)?": "a-1",
}


@st.composite
def matching_targets(draw, pattern):
    seed = _MATCHING_SEED[pattern]
    prefix = draw(st.text(alphabet="abhu/-0123456789xy", max_size=8))
    suffix = draw(st.text(alphabet="abhu/-0123456789xy", max_size=8))
    return prefix + seed + suffix


class JsBackreferenceConversionProperties(SimpleTestCase):
    @given(case=st.sampled_from(PATTERNS), data=st.data())
    # #171: transform_url("/", r"(.*)$", "$0") returned '\x00\x00'.
    @example(case=(r"(.*)$", 1), data=None)
    # #171: "$01" became "\01", a U+0001 control byte.
    @example(case=(r"(h)/(u)", 2), data=None)
    def test_conversion_never_introduces_a_character_absent_from_target_and_template(
        self, case, data
    ):
        pattern, group_count = case
        if data is None:
            # The two #171 regressions above: literal templates the free-form
            # strategy is unlikely to draw unaided.
            template, target = {
                (r"(.*)$", 1): ("$0", "/"),
                (r"(h)/(u)", 2): ("$01/$2", "http://h/u/p/1.ts"),
            }[case]
        elif data.draw(st.booleans()):
            pieces = data.draw(js_templates(group_count))
            template = "".join(text for _, _, text in pieces)
            target = data.draw(matching_targets(pattern))
        else:
            template = data.draw(templates)
            target = data.draw(targets)
        result = _apply(pattern, template, target)
        if result is None:
            return
        self.assertLessEqual(set(result), set(target) | set(template), repr(result))

    @given(data=st.data(), case=st.sampled_from(PATTERNS), target=targets)
    @example(
        data=None,
        case=(r"(h)/(u)", 2),
        target="http://h/u/p/1.ts",
    ).via("#171: $02-$01 must read groups 2 and 1, not octal escapes")
    def test_group_tokens_substitute_like_javascript_string_replace(self, data, case, target):
        pattern, group_count = case
        if data is None:
            pieces = [("group", 2, "$02"), ("literal", None, "-"), ("group", 1, "$01")]
        else:
            pieces = data.draw(js_templates(group_count))
        template = "".join(text for _, _, text in pieces)
        self.assertEqual(
            _apply(pattern, template, target),
            _javascript_replace(pattern, pieces, target),
            f"template={template!r}",
        )

    # "abcdefghijkl".replace(TWELVE_GROUPS, template), recorded in Node 22.
    TWELVE_GROUPS = r"(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)(l)"
    NODE_22_OUTPUTS = [
        ("$012", "a2"),  # $01 then a literal 2, not group 12
        ("$001", "$001"),  # no $0 token, and $00 is not a group
        ("$0012", "$0012"),
        ("[$100]", "[j0]"),  # at most two digits: $10 then a literal 0
        ("$12", "l"),
        ("$01", "a"),
        ("$1x", "ax"),
        ("$010", "a0"),
    ]

    def test_multi_digit_tokens_read_exactly_as_javascript_does(self):
        for template, expected in self.NODE_22_OUTPUTS:
            with self.subTest(template=template):
                self.assertEqual(
                    _apply(self.TWELVE_GROUPS, template, "abcdefghijkl"), expected
                )
