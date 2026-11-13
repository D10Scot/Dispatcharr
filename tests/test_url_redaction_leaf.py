"""The scrubber's modules are stdlib-only leaves, and its call graph is silent (spec T10)."""
import ast
import sys
from pathlib import Path

from django.test import SimpleTestCase

from dispatcharr import log_scrub, url_redaction, utils

ROOT = Path(__file__).resolve().parent.parent / "dispatcharr"
LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "trace", "fatal"}
LOGGERISH = {"logging", "logger", "log", "_logger", "LOGGER"}


def imported_names(path):
    tree = ast.parse(path.read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.append("." * node.level + (node.module or ""))
                continue
            for alias in node.names:
                names.append(f"{node.module}.{alias.name}")
    return names


def is_logging_call(node):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LEVELS:
        return False
    target = node.func.value
    if isinstance(target, ast.Name):
        return target.id in LOGGERISH
    return isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute) and target.func.attr == "getLogger"


class LeafTests(SimpleTestCase):
    ALLOWED_PROJECT = {"dispatcharr.url_redaction", "dispatcharr.log_scrub"}

    def assert_stdlib_only(self, path):
        for name in imported_names(path):
            root = name.split(".")[0]
            if name in self.ALLOWED_PROJECT or root in sys.stdlib_module_names:
                continue
            self.fail(f"non-stdlib import: {name} in {path.name}")

    def test_url_redaction_imports_only_the_standard_library(self):
        self.assert_stdlib_only(ROOT / "url_redaction.py")

    def test_log_scrub_imports_only_the_standard_library_and_url_redaction(self):
        self.assert_stdlib_only(ROOT / "log_scrub.py")

    def test_utils_reexports_the_very_same_objects(self):
        self.assertIs(utils.REDACTED, url_redaction.REDACTED)
        self.assertIs(utils.SENSITIVE_QUERY_KEYS, url_redaction.SENSITIVE_QUERY_KEYS)
        self.assertIs(utils.XTREAM_PATH_PREFIXES, url_redaction.XTREAM_PATH_PREFIXES)

    def test_the_contained_keys_are_members_of_the_shared_set(self):
        self.assertTrue(set(log_scrub._CONTAINED_KEYS) <= set(url_redaction.SENSITIVE_QUERY_KEYS))

    def module_functions(self):
        tree = ast.parse((ROOT / "log_scrub.py").read_text())
        return tree, {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def test_no_logging_call_is_reachable_from_the_factory(self):
        tree, functions = self.module_functions()
        install = functions["install"]
        factory = next(n for n in ast.walk(install) if isinstance(n, ast.FunctionDef) and n.name == "factory")
        pending = [factory, functions["_scrub_record"]]
        seen = set()
        while pending:
            fn = pending.pop()
            for node in ast.walk(fn):
                if is_logging_call(node):
                    self.fail(f"logging call reachable from the factory: {fn.name}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    callee = node.func.id
                    if callee in functions and callee not in seen:
                        seen.add(callee)
                        pending.append(functions[callee])
        self.assertIn("scrub_text", seen)  # the walk really reached the scanner

    def test_the_only_logging_call_is_the_constant_warning_in_ensure_installed(self):
        tree, functions = self.module_functions()
        found = [
            (fn.name, node)
            for fn in functions.values()
            for node in ast.walk(fn)
            if is_logging_call(node)
        ]
        self.assertEqual([name for name, _ in found], ["ensure_installed"])
        call = found[0][1]
        self.assertEqual(call.func.attr, "warning")
        self.assertEqual(len(call.args), 1)
        self.assertIsInstance(call.args[0], ast.Constant)
        self.assertEqual(call.keywords, [])
