#!/usr/bin/env python3
"""Run every metrics collector and emit per-family JSONL rows.

Each row: {"timestamp": <ISO-8601 UTC>, "commit_sha": <sha>, "family": <name>,
"metrics": {...}} appended to <out-dir>/<family>.jsonl.

Appends are idempotent on (commit_sha, family): an existing row for the same
commit and family is left untouched and the new one skipped, so re-running a
backfill or a CI retry never duplicates history.

Families are checkout-scanning (stdlib AST/grep over --repo-root, safe in a
historical worktree) or external (coverage: no script, metrics arrive via
--extra-metrics from the workflow's coverage job). GitHub-backed data is not a
family any more — see collect_events.py.

Every family runs independently: one family's script failing does not stop
the others from running. Failures are collected and reported, and the
process exits 1 at the end if any family failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

# family -> collector script, or None for a family whose metrics arrive only
# via --extra-metrics (coverage: produced by the workflow's coverage job).
FAMILIES: dict[str, str | None] = {
    "code_health": "collect_code_health.py",
    "architecture": "collect_architecture.py",
    "tests": "collect_tests.py",
    "coverage": None,
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
        "--skip-families",
        default="",
        help="Comma-separated family names to skip entirely.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated family names to run (default: all in FAMILIES).",
    )
    parser.add_argument(
        "--extra-metrics",
        action="append",
        default=[],
        metavar="FAMILY=PATH",
        help="Merge additional key/value pairs from a JSON file into a "
        "family's metrics dict before writing (e.g. "
        "'coverage=/tmp/coverage-row.json' to supply the external `coverage` "
        "family's metrics, produced by coverage_summary.py from a real "
        "backend + frontend suite run under coverage — see metrics.yml's "
        "coverage job). Repeatable.",
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

    only = {f.strip() for f in args.only.split(",") if f.strip()}
    unknown = only - set(FAMILIES)
    if unknown:
        print(f"unknown family in --only: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    repo_root = args.repo_root.resolve()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = Path(__file__).resolve().parent
    skip = {f.strip() for f in args.skip_families.split(",") if f.strip()}

    # Parsed lazily per family inside the loop below (a missing/malformed
    # file must fail only the family that consumes it, not every family).
    extra_metrics_paths: dict[str, str] = {}
    for entry in args.extra_metrics:
        family, _, path = entry.partition("=")
        extra_metrics_paths[family] = path

    sha = args.commit_sha or git_head_sha(repo_root)
    timestamp = args.commit_date or dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds"
    )

    overrides = dict(
        item.split("=", 1) for item in os.environ.get("METRICS_COLLECTOR_OVERRIDE", "").split(",") if "=" in item
    )
    failures: list[str] = []
    for family, script in FAMILIES.items():
        if only and family not in only:
            continue
        if family in skip:
            print(f"skip {family}: excluded via --skip-families", file=sys.stderr)
            continue
        out_path = out_dir / f"{family}.jsonl"
        if sha in existing_keys(out_path):
            print(f"skip {family}: row for {sha[:12]} already present", file=sys.stderr)
            continue
        try:
            if script is None:
                if family not in extra_metrics_paths:
                    print(f"skip {family}: external family, no --extra-metrics given", file=sys.stderr)
                    continue
                metrics = {}
            else:
                script_path = Path(overrides.get(family, str(scripts_dir / script)))
                result = subprocess.run(
                    [sys.executable, str(script_path), "--repo-root", str(repo_root)],
                    capture_output=True, text=True,
                )
                if result.stderr:
                    sys.stderr.write(result.stderr)
                if result.returncode != 0:
                    raise RuntimeError(f"{script_path} exited {result.returncode}")
                metrics = json.loads(result.stdout)
            if family in extra_metrics_paths:
                extra = json.loads(Path(extra_metrics_paths[family]).read_text(encoding="utf-8"))
                metrics.update(extra)
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"FAILED {family}: {exc}", file=sys.stderr)
            failures.append(family)
            continue
        row = {"timestamp": timestamp, "commit_sha": sha, "family": family, "metrics": metrics}
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {family} row for {sha[:12]}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} famil{'y' if len(failures) == 1 else 'ies'} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
