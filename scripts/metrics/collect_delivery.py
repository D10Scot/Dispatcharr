#!/usr/bin/env python3
"""Metric family: delivery.

GitHub-API-backed CI health and PR flow over a trailing 30-day window.
Like ``collect_security.py`` this needs network access and is NOT run by
`backfill.py` — the series starts at first collection (see ``_notes``).

- ci_by_workflow: ``{workflow_name: {run_count, pass_rate, median_duration_seconds}}``
  for every workflow with at least one completed run in the window. Only
  ``completed`` runs are considered; pass_rate = success / (success + failure)
  — runs with conclusion ``cancelled``/``skipped``/``neutral``/``timed_out``
  contribute to run_count but not to the pass_rate denominator (a cancelled
  run is not a verdict on the code). Duration is
  ``updated_at - run_started_at`` in seconds, median across counted runs.
- pr_lead_time_seconds: ``{median, p90, count}`` open->merge time (seconds)
  over PRs merged in the trailing 30 days.
- pr_lead_time_by_author_type: the same shape, split into ``human`` and
  ``agent`` sub-dicts.

Human vs agent heuristic (documented here since it's a judgment call, not an
API fact): a merged PR counts as **agent**-authored only if it was opened by
a bot account (``author.is_bot`` true, e.g. ``github-actions[bot]``) or its
head branch matches a known fully-autonomous gh-aw pipeline pattern
(``^copilot/``, ``^agentics/``, or contains ``remediation`` — the
issue-remediation workflow's branch naming). Everything else counts as
**human**, INCLUDING branches created by a person driving Copilot CLI
interactively (e.g. this fork's own ``dionmm-*`` branches) — a human is
steering those sessions turn-by-turn, so they are development work with AI
assistance, not autonomous agent output. At the time this collector was
written, this repo has zero agent-authored merged PRs (the gh-aw pipeline is
new); expect ``agent.count == 0`` until issue-remediation starts merging.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics

from _gh import gh_api, run_gh, repo_arg
import json

WINDOW_DAYS = 30
AGENT_BRANCH_RE = re.compile(r"^(copilot/|agentics/)|remediation")


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))
    return ordered[idx]


def _summary(seconds: list[float]) -> dict:
    return {
        "median": _median(seconds),
        "p90": _p90(seconds),
        "count": len(seconds),
    }


def ci_by_workflow(repo: str, since: dt.datetime) -> dict[str, dict]:
    workflows = gh_api(repo, "/actions/workflows").get("workflows", [])
    result: dict[str, dict] = {}
    since_str = since.strftime("%Y-%m-%d")
    for wf in workflows:
        runs = gh_api(
            repo,
            f"/actions/workflows/{wf['id']}/runs",
            params={"created": f">={since_str}", "per_page": "100"},
        ).get("workflow_runs", [])
        completed = [r for r in runs if r.get("status") == "completed"]
        if not completed:
            continue
        durations = []
        pass_count = 0
        verdict_count = 0
        for run in completed:
            started = run.get("run_started_at")
            updated = run.get("updated_at")
            if started and updated:
                durations.append((_parse_ts(updated) - _parse_ts(started)).total_seconds())
            conclusion = run.get("conclusion")
            if conclusion in ("success", "failure"):
                verdict_count += 1
                if conclusion == "success":
                    pass_count += 1
        result[wf["name"]] = {
            "run_count": len(completed),
            "pass_rate": (pass_count / verdict_count) if verdict_count else None,
            "median_duration_seconds": _median(durations),
        }
    return result


def _is_agent_pr(pr: dict) -> bool:
    author = pr.get("author") or {}
    if author.get("is_bot"):
        return True
    head_ref = pr.get("headRefName") or ""
    return bool(AGENT_BRANCH_RE.search(head_ref))


def merged_prs(repo: str, since: dt.datetime) -> list[dict]:
    since_str = since.strftime("%Y-%m-%d")
    stdout = run_gh(
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--search",
        f"merged:>={since_str}",
        "--limit",
        "200",
        "--json",
        "number,createdAt,mergedAt,headRefName,author,isDraft",
    )
    return json.loads(stdout)


def pr_lead_times(prs: list[dict]) -> tuple[list[float], list[float], list[float]]:
    all_seconds: list[float] = []
    human_seconds: list[float] = []
    agent_seconds: list[float] = []
    for pr in prs:
        created = pr.get("createdAt")
        merged = pr.get("mergedAt")
        if not created or not merged:
            continue
        lead = (_parse_ts(merged) - _parse_ts(created)).total_seconds()
        all_seconds.append(lead)
        if _is_agent_pr(pr):
            agent_seconds.append(lead)
        else:
            human_seconds.append(lead)
    return all_seconds, human_seconds, agent_seconds


def main() -> None:
    from _common import emit

    repo = repo_arg(__doc__)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=WINDOW_DAYS)

    ci = ci_by_workflow(repo, since)
    prs = merged_prs(repo, since)
    all_seconds, human_seconds, agent_seconds = pr_lead_times(prs)

    emit(
        {
            "ci_by_workflow": ci,
            "pr_lead_time_seconds": _summary(all_seconds),
            "pr_lead_time_by_author_type": {
                "human": _summary(human_seconds),
                "agent": _summary(agent_seconds),
            },
            "_notes": (
                "not backfillable: series starts at first collection "
                f"(trailing {WINDOW_DAYS}-day window computed at run time, no "
                "historical snapshot exists per commit). Human/agent split "
                "heuristic documented in this file's module docstring."
            ),
        }
    )


if __name__ == "__main__":
    main()
