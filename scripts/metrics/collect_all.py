#!/usr/bin/env python3
"""Run every metrics collector and emit per-family JSONL rows.

Each row: {"timestamp": <ISO-8601 UTC>, "commit_sha": <sha>, "family": <name>,
"metrics": {...}} appended to <out-dir>/<family>.jsonl.

Appends are idempotent on (commit_sha, family): an existing row for the same
commit and family is left untouched and the new one skipped, so re-running a
backfill or a CI retry never duplicates history.
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
}


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

    sha = args.commit_sha or git_head_sha(repo_root)
    timestamp = args.commit_date or dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )

    for family, script in FAMILIES.items():
        out_path = out_dir / f"{family}.jsonl"
        if sha in existing_keys(out_path):
            print(f"skip {family}: row for {sha[:12]} already present", file=sys.stderr)
            continue
        result = subprocess.run(
            [sys.executable, str(scripts_dir / script), "--repo-root", str(repo_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stderr:
            sys.stderr.write(result.stderr)
        row = {
            "timestamp": timestamp,
            "commit_sha": sha,
            "family": family,
            "metrics": json.loads(result.stdout),
        }
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {family} row for {sha[:12]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
