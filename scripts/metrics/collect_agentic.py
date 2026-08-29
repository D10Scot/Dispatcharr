#!/usr/bin/env python3
"""Metric family: agentic.

GitHub-API-backed counts for the label-driven agentic pipeline (domain-fuzz-
campaign -> issue-triage -> issue-remediation, see CLAUDE.md). Needs network
access, so it is NOT run by `backfill.py` — the series starts at first
collection (see ``_notes``).

- issues_by_label: for each of the five triage labels, the four priority
  labels (``priority:p0``..``priority:p3``), and ``fuzzing``, ``{open,
  closed}`` issue counts (current state, any label they have ever had is
  not tracked here — only the label the issue currently carries). A label
  that doesn't exist on the repo yet, or has no issues, reports
  ``{"open": 0, "closed": 0}`` — this is a legitimate value, not an error.
- median_time_to_triage_seconds: median seconds between an issue's creation
  and the timeline event where the ``needs-triage`` label was removed
  (``unlabeled`` event), across every issue where that event has happened.
  Computed by walking the timeline of every issue in the repo (capped at the
  most recent ``ISSUE_SCAN_LIMIT`` issues to bound API calls — this repo
  currently has well under that many issues total) and finding the first
  ``unlabeled``/``needs-triage`` event. Issues that never had the label
  removed (still in ``needs-triage``, or never labelled at all) don't
  contribute a sample. ``null`` when no issue has ever had the label removed.
"""

from __future__ import annotations

import datetime as dt
import statistics

from _gh import gh_api, run_gh, repo_arg
import json

LABELS = (
    "needs-triage",
    "needs-info",
    "ready-for-agent",
    "ready-for-human",
    "wontfix",
    "priority:p0",
    "priority:p1",
    "priority:p2",
    "priority:p3",
    "fuzzing",
)
ISSUE_SCAN_LIMIT = 200


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def issues_by_label(repo: str) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for label in LABELS:
        counts = {"open": 0, "closed": 0}
        for state in ("open", "closed"):
            stdout = run_gh(
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                state,
                "--label",
                label,
                "--limit",
                "500",
                "--json",
                "number",
            )
            counts[state] = len(json.loads(stdout))
        result[label] = counts
    return result


def median_time_to_triage_seconds(repo: str) -> float | None:
    stdout = run_gh(
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--limit",
        str(ISSUE_SCAN_LIMIT),
        "--json",
        "number,createdAt",
    )
    issues = json.loads(stdout)
    samples: list[float] = []
    for issue in issues:
        number = issue["number"]
        created = _parse_ts(issue["createdAt"])
        timeline = gh_api(repo, f"/issues/{number}/timeline")
        for event in timeline:
            if event.get("event") == "unlabeled" and (event.get("label") or {}).get(
                "name"
            ) == "needs-triage":
                removed = _parse_ts(event["created_at"])
                samples.append((removed - created).total_seconds())
                break
    return statistics.median(samples) if samples else None


def main() -> None:
    from _common import emit

    repo = repo_arg(__doc__)

    emit(
        {
            "issues_by_label": issues_by_label(repo),
            "median_time_to_triage_seconds": median_time_to_triage_seconds(repo),
            "_notes": (
                "not backfillable: series starts at first collection (live "
                "issue/label state, no historical snapshot exists per commit). "
                f"Time-to-triage scans at most the {ISSUE_SCAN_LIMIT} most "
                "recent issues to bound API calls."
            ),
        }
    )


if __name__ == "__main__":
    main()
