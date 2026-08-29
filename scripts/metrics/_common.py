"""Shared helpers for the metrics collectors.

Stdlib-only on purpose: collectors must run on a bare checkout (CI runner
python3, historical worktrees during backfill) with no dependency install.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Directories never scanned, at any depth.
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
}


def iter_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """All files under *root* with one of *suffixes*, skipping excluded dirs."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        out.append(path)
    return out


def parse_python(path: Path) -> ast.AST | None:
    """Parse a Python file, returning None on syntax errors (old commits may
    contain files newer interpreters reject; a metrics run must not die)."""
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        print(f"warning: syntax error, skipping {path}", file=sys.stderr)
        return None


def is_test_path(rel: Path) -> bool:
    parts = rel.parts
    return (
        "tests" in parts
        or rel.name.startswith("test_")
        or rel.name.endswith("_test.py")
    )


def repo_root_arg(description: str) -> Path:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root to scan (default: current directory)",
    )
    args = parser.parse_args()
    return args.repo_root.resolve()


def emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
