#!/usr/bin/env python3
"""Metric family: tests.

Counts of tests as written (not as run — no suite execution here):

- backend_test_count: ``test_*`` methods/functions in backend test files,
  counted via AST (Hypothesis-parametrised tests count once each).
- frontend_test_count: ``it(``/``test(`` call sites (incl. ``.each``/
  ``.skip`` variants) in ``frontend/**/*.test.{js,jsx}``.
- e2e_scenario_count: Playwright ``test(`` call sites in
  ``e2e/tests/**/*.spec.ts``.
- e2e_greybox_test_count: the subset under ``tests/streaming-greybox/``.
- hypothesis_property_test_count: ``@given``-decorated tests anywhere in
  backend test files.

- coverage: null — deliberately deferred. Coverage %s require a full
  backend matrix run plus a frontend vitest coverage run per data point,
  which is neither cheap per-collection nor backfillable against historical
  commits without executing their suites. Wire into M2 from CI artifacts.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from _common import emit, is_test_path, iter_files, parse_python, repo_root_arg

JS_TEST_RE = re.compile(r"(?:^|[^\w.])(?:it|test)(?:\.(?:each|skip|only|todo|fails|concurrent)(?:\([^)]*\))?)?\s*\(", re.M)


def count_js_tests(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        total += len(JS_TEST_RE.findall(text))
    return total


def main() -> None:
    root = repo_root_arg(__doc__)

    backend_test_count = 0
    hypothesis_tests = 0
    for path in iter_files(root, (".py",)):
        rel = path.relative_to(root)
        if rel.parts[0] in {"e2e", "e2e-upstream", "frontend"} or not is_test_path(rel):
            continue
        tree = parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test")
            ):
                backend_test_count += 1
                if any(_is_given_decorator(d) for d in node.decorator_list):
                    hypothesis_tests += 1

    frontend_dir = root / "frontend"
    frontend_files = [
        p
        for p in iter_files(frontend_dir, (".js", ".jsx"))
        if ".test." in p.name
    ] if frontend_dir.is_dir() else []
    frontend_test_count = count_js_tests(frontend_files)

    e2e_tests_dir = root / "e2e" / "tests"
    e2e_files = (
        [p for p in iter_files(e2e_tests_dir, (".ts",)) if p.name.endswith(".spec.ts")]
        if e2e_tests_dir.is_dir()
        else []
    )
    e2e_scenario_count = count_js_tests(e2e_files)
    e2e_greybox = count_js_tests(
        [p for p in e2e_files if "streaming-greybox" in p.parts]
    )

    emit(
        {
            "backend_test_count": backend_test_count,
            "frontend_test_count": frontend_test_count,
            "e2e_scenario_count": e2e_scenario_count,
            "e2e_greybox_test_count": e2e_greybox,
            "hypothesis_property_test_count": hypothesis_tests,
            "coverage": None,
            "_notes": "coverage deferred to M2 (requires suite execution; see docstring)",
        }
    )


def _is_given_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "given"
    if isinstance(target, ast.Attribute):
        return target.attr == "given"
    return False


if __name__ == "__main__":
    main()
