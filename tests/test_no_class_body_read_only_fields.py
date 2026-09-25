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

WHAT COUNTS. Only a `read_only_fields = [...]` assignment made directly in a
class's own body counts as a violation. The identical assignment made
directly in that class's own `class Meta:` body is correct and is not
flagged -- the scan skips any `ClassDef` named `Meta` before checking its
body, so it never descends into a legitimate declaration while walking the
outer class that contains it.
"""

import ast
import pathlib

from django.test import SimpleTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Every non-test serializers.py in the tree: one per Django app plus core's.
SERIALIZER_FILES = sorted(REPO_ROOT.glob("apps/*/serializers.py")) + [
    REPO_ROOT / "core" / "serializers.py"
]


def _class_body_read_only_fields(path):
    """Yield (lineno, class_name) for each `read_only_fields = ...` assignment
    made directly in a class body other than `Meta`'s own."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name == "Meta":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
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
