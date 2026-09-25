"""Property tests for ``convert_js_numbered_backreferences`` (issues #218, #69; seam #171).

Surface at seed a54b09a9: ``apps/m3u/utils.py:13``. The helper turns a
JavaScript-style replacement template (``$1``) into a Python ``regex``
template, and the auto-sync rename feeds the result to ``regex.sub``
(``apps/m3u/tasks.py:2608``). These properties exercise it the way the rename
does -- ``regex.sub(pattern, convert(template), target)`` -- because the
defect (#171) is what the converted template *does*, not what it looks like.

Both properties hold under either reading of ``$0`` that C-4 offers the user
(literal ``$0``, the default, or the whole match), so they do not depend on
that ruling:

1. The output contains no character that is in neither the target nor the
   template. Before C-4, ``$0`` became ``\\0`` (a NUL byte) and ``$01`` became
   ``\\01`` (U+0001).
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
code under test). The one remaining divergence is JavaScript's fallback
when group ``nn`` does not exist (``$10`` with two groups reads ``$1`` then
``0``); the helper refuses it instead, and C-4 records that as pre-existing,
so it is not asserted here.
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
# backslash (a JS template has no backslash escapes; that is outside #171).
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


class JsBackreferenceConversionProperties(SimpleTestCase):
    @given(case=st.sampled_from(PATTERNS), template=templates, target=targets)
    # #171: transform_url("/", r"(.*)$", "$0") returned '\x00\x00'.
    @example(case=(r"(.*)$", 1), template="$0", target="/")
    # #171: "$01" became "\01", a U+0001 control byte.
    @example(case=(r"(h)/(u)", 2), template="$01/$2", target="http://h/u/p/1.ts")
    def test_conversion_never_introduces_a_character_absent_from_target_and_template(
        self, case, template, target
    ):
        pattern, _ = case
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
