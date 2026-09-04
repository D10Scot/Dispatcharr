#!/usr/bin/env python3
"""Backfill metrics history over first-parent commits on main.

Runs the collectors against BASELINE_SHA (fd413f0c, the v0.29.0 divergence
point) and every first-parent commit after it up to --ref (default: main),
using a temporary detached git worktree per commit. Rows land in --out-dir
via collect_all.py, timestamped with each commit's author date; appends are
idempotent, so re-running after new merges only adds the new commits.

GitHub-backed data (formerly the security/delivery/agentic families) is
collected separately by collect_events.py and is not part of this per-commit
loop: it reports live repo/API state, not a fact about a specific historical
commit, so attributing today's CodeQL alert count to a commit from three
months ago would be misleading.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

BASELINE_SHA = "fd413f0c"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ref", default="main", help="End of the range (default: main)")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    scripts_dir = Path(__file__).resolve().parent
    baseline = git(repo, "rev-parse", BASELINE_SHA)
    commits = [baseline] + git(
        repo, "rev-list", "--first-parent", "--reverse", f"{baseline}..{args.ref}"
    ).splitlines()

    print(f"backfilling {len(commits)} commits", file=sys.stderr)
    failures = 0
    for sha in commits:
        author_date = git(repo, "show", "-s", "--format=%aI", sha)
        with tempfile.TemporaryDirectory(prefix="metrics-backfill-") as tmp:
            worktree = Path(tmp) / "wt"
            git(repo, "worktree", "add", "--detach", str(worktree), sha)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(scripts_dir / "collect_all.py"),
                        "--repo-root",
                        str(worktree),
                        "--out-dir",
                        str(args.out_dir),
                        "--commit-sha",
                        sha,
                        "--commit-date",
                        author_date,
                        # coverage is external (no script, no --extra-metrics
                        # here) and never backfilled — see the module
                        # docstring. Without --only, every historical commit
                        # prints a "skip coverage: external family" line.
                        "--only",
                        "code_health,architecture,tests",
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                print(f"error: collectors failed at {sha[:12]}: {exc}", file=sys.stderr)
                failures += 1
            finally:
                git(repo, "worktree", "remove", "--force", str(worktree))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
