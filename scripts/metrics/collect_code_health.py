#!/usr/bin/env python3
"""Metric family: code_health.

Counts grep/AST-style debt markers across backend Python. Definitions are
frozen here so the time series stays self-consistent:

- bare_except: ``except:`` handlers (AST ExceptHandler with no type).
- except_exception: handlers catching exactly ``Exception``.
- except_pass_handlers: handlers (of any type) whose entire body is ``pass``.
- function_local_imports: import statements nested inside a function body.
- os_environ_reads: expressions referencing ``os.environ`` (attribute access).
- loc_per_app: non-blank Python lines per top-level backend package.
- frontend_loc: non-blank lines in frontend/src js/jsx files.

Scope: every ``*.py`` in the repo outside excluded dirs, tests included
(debt in tests is still debt); per-metric non-test variants are not split
out to keep the series simple.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import emit, iter_files, parse_python, repo_root_arg

BACKEND_PACKAGES = ("apps", "core", "dispatcharr", "scripts")


def count_nonblank_lines(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    )


def main() -> None:
    root = repo_root_arg(__doc__)
    py_files = iter_files(root, (".py",))

    bare_except = 0
    except_exception = 0
    except_pass = 0
    function_local_imports = 0
    os_environ_reads = 0
    loc_per_app: dict[str, int] = {}

    for path in py_files:
        rel = path.relative_to(root)
        tree = parse_python(path)
        if tree is None:
            continue

        top = rel.parts[0]
        if top in BACKEND_PACKAGES:
            key = (
                f"{rel.parts[0]}.{rel.parts[1]}"
                if top == "apps" and len(rel.parts) > 1
                else top
            )
            loc_per_app[key] = loc_per_app.get(key, 0) + count_nonblank_lines(path)

        function_local_imports += _imports_under_functions(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    bare_except += 1
                elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    except_exception += 1
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    except_pass += 1
            elif isinstance(node, ast.Attribute):
                if (
                    node.attr == "environ"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "os"
                ):
                    os_environ_reads += 1

    emit(
        {
            "bare_except": bare_except,
            "except_exception": except_exception,
            "except_pass_handlers": except_pass,
            "function_local_imports": function_local_imports,
            "os_environ_reads": os_environ_reads,
            "loc_per_app": dict(sorted(loc_per_app.items())),
            "frontend_loc": frontend_loc(root),
        }
    )


def _imports_under_functions(tree: ast.AST) -> int:
    """Import statements with a function ancestor, each counted once."""
    count = 0

    def visit(node: ast.AST, inside_function: bool) -> None:
        nonlocal count
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)) and inside_function:
                count += 1
            visit(
                child,
                inside_function
                or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)),
            )

    visit(tree, False)
    return count


def frontend_loc(root: Path) -> int:
    src = root / "frontend" / "src"
    if not src.is_dir():
        return 0
    return sum(count_nonblank_lines(p) for p in iter_files(src, (".js", ".jsx")))


if __name__ == "__main__":
    main()
