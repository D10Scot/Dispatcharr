#!/usr/bin/env python3
"""Run every metrics collector and emit per-family JSONL rows.

Each row: {"timestamp": <ISO-8601 UTC>, "commit_sha": <sha>, "family": <name>,
"metrics": {...}} appended to <out-dir>/<family>.jsonl.

Appends are idempotent on (commit_sha, family): an existing row for the same
commit and family is left untouched and the new one skipped, so re-running a
backfill or a CI retry never duplicates history.

Two kinds of families:
- checkout-scanning (code_health, architecture, tests): stdlib-only, run
  against --repo-root, safe to run in a historical worktree (backfill.py).
- GitHub-API-backed (security, delivery, agentic — see API_FAMILIES): call
  `gh` against --repo, report *live* repo/API state rather than a fact about
  the given commit, and are therefore excluded from backfill.py's per-commit
  loop via --skip-families.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

FAMILIES = {
    "code_health": "collect_code_health.py",
    "architecture": "collect_architecture.py",
    "tests": "collect_tests.py",
    "security": "collect_security.py",
    "delivery": "collect_delivery.py",
    "agentic": "collect_agentic.py",
}

# Families that call the GitHub API (via `gh`) instead of scanning a
# checkout. They report live repo state, not a fact about a specific commit,
# so they cannot be backfilled against historical commits and are excluded
# by default there (see backfill.py, which passes --skip-families for these).
API_FAMILIES = {"security", "delivery", "agentic"}


def git_head_sha(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def existing_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        keys.add(row["commit_sha"])
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--repo",
        default="D10Scot/Dispatcharr",
        help="owner/repo passed to the GitHub-API families (security, "
        "delivery, agentic); irrelevant to the checkout-scanning families.",
    )
    parser.add_argument(
        "--skip-families",
        default="",
        help="Comma-separated family names to skip entirely (e.g. "
        "backfill.py passes the API_FAMILIES here, since they report live "
        "repo state and cannot be attributed to a historical commit).",
    )
    parser.add_argument(
        "--extra-metrics",
        action="append",
        default=[],
        metavar="FAMILY=PATH",
        help="Merge additional key/value pairs from a JSON file into a "
        "family's metrics dict before writing (e.g. "
        "'tests=/tmp/coverage.json' to fold in a weekly-only vitest "
        "coverage number without collect_tests.py itself executing the "
        "suite). Repeatable.",
    )
    parser.add_argument(
        "--commit-sha",
        default=None,
        help="SHA to record (default: HEAD of --repo-root)",
    )
    parser.add_argument(
        "--commit-date",
        default=None,
        help="ISO-8601 timestamp to record (default: now UTC). "
        "Backfill passes the commit author date so charts plot true history.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = Path(__file__).resolve().parent
    skip = {f.strip() for f in args.skip_families.split(",") if f.strip()}

    extra_metrics: dict[str, dict] = {}
    for entry in args.extra_metrics:
        family, _, path = entry.partition("=")
        extra_metrics[family] = json.loads(Path(path).read_text(encoding="utf-8"))

    sha = args.commit_sha or git_head_sha(repo_root)
    timestamp = args.commit_date or dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )

    for family, script in FAMILIES.items():
        if family in skip:
            print(f"skip {family}: excluded via --skip-families", file=sys.stderr)
            continue
        out_path = out_dir / f"{family}.jsonl"
        if sha in existing_keys(out_path):
            print(f"skip {family}: row for {sha[:12]} already present", file=sys.stderr)
            continue
        script_args = (
            ["--repo", args.repo] if family in API_FAMILIES else ["--repo-root", str(repo_root)]
        )
        result = subprocess.run(
            [sys.executable, str(scripts_dir / script), *script_args],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stderr:
            sys.stderr.write(result.stderr)
        metrics = json.loads(result.stdout)
        if family in extra_metrics:
            metrics.update(extra_metrics[family])
        row = {
            "timestamp": timestamp,
            "commit_sha": sha,
            "family": family,
            "metrics": metrics,
        }
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {family} row for {sha[:12]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
