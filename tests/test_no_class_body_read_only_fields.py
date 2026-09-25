"""AST scan: `read_only_fields` must live in `Meta`, where DRF reads it.

WHY THIS EXISTS (#15). `serializers.ModelSerializer` only consults
`Meta.read_only_fields`. An attribute of the same name assigned directly in
the serializer class body -- a sibling of `class Meta`, not a member of it --
is an ordinary class attribute DRF never looks at: the fields it names stay
writable over the API. Neither DRF nor any linter run in this repo warns
about it, and the mistake recurred independently at four call sites across
three apps (`M3UAccountSerializer`, `EPGSourceSerializer`,
`EPGDataSerializer`, `StreamSerializer`) before this guard existed. This is
a repo-wide scan rather than four one-off tests because the failure mode is
"the same typo, repeated", and a new serializer can make it again.

WHAT COUNTS. Only a `read_only_fields = [...]` (or an annotated
`read_only_fields: list = [...]`) assignment made directly in the body of a
class that looks like a serializer counts as a violation: one with a nested
`class Meta`, or with a base class whose name ends in `Serializer`. That
excludes a helper base meant to be inherited by an actual `Meta` -- a
`class BaseMeta:` shared across several serializers' `Meta`s, say -- which
has neither trait and is not itself a serializer class body. The identical
assignment made directly in a class's own `class Meta:` body is correct and
is not flagged -- the scan skips any `ClassDef` named `Meta` before checking
its body, so it never descends into a legitimate declaration while walking
the outer class that contains it.
"""

import ast
import pathlib

from django.test import SimpleTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Every non-test serializers.py in the tree, at any depth under apps/ (so
# apps/proxy/relay_serializers.py and a nested app's own serializers.py are
# both included, not just one literally named serializers.py one level
# down), plus core's.
SERIALIZER_FILES = sorted(
    p for p in REPO_ROOT.glob("apps/**/*serializers.py") if "tests" not in p.parts
) + [REPO_ROOT / "core" / "serializers.py"]


def _base_name(base):
    """The trailing identifier of a base-class expression: `Name` for
    `ModelSerializer`, `Attribute.attr` for `serializers.ModelSerializer`."""
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Name):
        return base.id
    return None


def _looks_like_serializer_class(node):
    has_nested_meta = any(
        isinstance(child, ast.ClassDef) and child.name == "Meta" for child in node.body
    )
    has_serializer_base = any(
        (_base_name(base) or "").endswith("Serializer") for base in node.bases
    )
    return has_nested_meta or has_serializer_base


def _class_body_read_only_fields(path):
    """Yield (lineno, class_name) for each `read_only_fields = ...` (plain or
    annotated) assignment made directly in the body of a serializer-like
    class, other than `Meta`'s own body."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name == "Meta":
            continue
        if not _looks_like_serializer_class(node):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "read_only_fields":
                    yield stmt.lineno, node.name


class NoClassBodyReadOnlyFieldsTest(SimpleTestCase):
    def test_no_serializer_declares_read_only_fields_outside_meta(self):
        violations = []
        for path in SERIALIZER_FILES:
            self.assertTrue(path.is_file(), f"expected serializers file missing: {path}")
            for lineno, class_name in _class_body_read_only_fields(path):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}:{lineno} ({class_name})")

        self.assertEqual(
            violations,
            [],
            "read_only_fields assigned in the serializer class body, where "
            "DRF never reads it -- move it into that class's Meta: "
            + ", ".join(violations),
        )
