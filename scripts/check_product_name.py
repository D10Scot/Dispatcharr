#!/usr/bin/env python3
"""Ratchet on the old product name (Mino rename, PR R1).

Counts case-insensitive occurrences of the old name per tracked file and
compares them with scripts/product_name_allowlist.txt (`<count>\\t<path>`
lines). Fails when a file's count rises above its entry, or when a file has
hits and no entry. A file whose count fell is reported with a reminder to run
`--write`, which regenerates the allowlist from the tree.

Run from anywhere inside the repository: the root is `git rev-parse
--show-toplevel` of the current directory.

Skipped, by design:
  * RECORD_GLOBS: the decision records the spec's rule R-1 names. They keep
    the old name forever. This list is the one place R-1 is enforced; editing
    it is how the rule is amended.
  * ALLOWLIST itself: it names paths that contain the word, so it would count
    against itself.
  * binary files (a NUL byte in the first 8000 bytes), symlinks, and paths
    git lists but the tree no longer holds.
"""

import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

# R-1 (docs/superpowers/specs/2026-10-28-mino-rename-design.md). fnmatch's "*"
# crosses "/", so "dir/*" covers the whole subtree.
RECORD_GLOBS = [
    "docs/adr/*",
    "docs/superpowers/specs/*",
    "docs/superpowers/plans/*",
    "docs/superpowers/analysis/*",
    "docs/comparisons/*",
    "CHANGELOG.md",
]

ALLOWLIST = "scripts/product_name_allowlist.txt"

# The old product name, matched case-insensitively.
NAME = re.compile(rb"dispatcharr", re.IGNORECASE)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    ).stdout


def is_record(path):
    return any(fnmatch.fnmatchcase(path, glob) for glob in RECORD_GLOBS)


def count_tree(root):
    counts = {}
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", "surrogateescape")
        if path == ALLOWLIST or is_record(path):
            continue
        full = Path(root) / path
        if full.is_symlink() or not full.is_file():
            continue
        data = full.read_bytes()
        if b"\0" in data[:8000]:
            continue
        n = len(NAME.findall(data))
        if n:
            counts[path] = n
    return counts


def read_allowlist(root):
    entries = {}
    allow = Path(root) / ALLOWLIST
    if not allow.is_file():
        return entries
    for number, line in enumerate(allow.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        count, sep, path = line.partition("\t")
        if not sep or not count.isdigit() or not path:
            raise ValueError(
                f"{ALLOWLIST}:{number}: expected `<count>\\t<path>`, got {line!r}"
            )
        entries[path] = int(count)
    return entries


def write_allowlist(root, counts):
    body = "".join(f"{n}\t{p}\n" for p, n in sorted(counts.items()))
    target = Path(root) / ALLOWLIST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def main(argv):
    write = "--write" in argv
    root = git(os.getcwd(), "rev-parse", "--show-toplevel").decode().strip()
    counts = count_tree(root)
    if write:
        write_allowlist(root, counts)
        print(f"wrote {len(counts)} entries to {ALLOWLIST}")
        return 0

    try:
        allowed = read_allowlist(root)
    except ValueError as err:
        print(err)
        return 1
    failures = [
        f"{path}: count {n}, allowed {allowed.get(path, 0)}"
        for path, n in sorted(counts.items())
        if n > allowed.get(path, 0)
    ]
    fell = [
        f"{path}: {allowed[path]} -> {counts.get(path, 0)}"
        for path in sorted(allowed)
        if counts.get(path, 0) < allowed[path]
    ]
    if failures:
        print("Old product name above the allowlist:")
        for line in failures:
            print(f"  {line}")
        print(f"Rename the new occurrences; do not raise {ALLOWLIST} without saying why.")
    if fell:
        print("Counts fell; run `python3 scripts/check_product_name.py --write` and commit:")
        for line in fell:
            print(f"  {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
