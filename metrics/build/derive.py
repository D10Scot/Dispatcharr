"""Every derived series, as pure functions of (events, defects, day, params).

"As of day D" means at the last second of D (UTC). Trailing windows are
(D - N days, D]. Each function returns a number or None when there is no
data to speak of — None is a gap on the chart, never a zero.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import statistics
from typing import Callable

from curated import Defect
from load import Dump, parse_ts

# A head ref counts as agent-driven when it starts with one of these
# prefixes (gh-aw's own branch shapes) or contains AGENT_BRANCH_MARKER (the
# gh-aw issue-remediation workflow's branch shape, e.g.
# "agentics/issue-remediation-9"). Deliberately NOT a bare "remediation"
# substring: that also matched human branches like
# "test/e2e-test-quality-remediation" (PR #139 on the live repo), which
# inflated agent_prs_merged and polluted the agent lead-time series with a
# human data point.
AGENT_BRANCH_PREFIXES = ("copilot/", "agentics/", "remediation")
AGENT_BRANCH_MARKER = "issue-remediation"


@dc.dataclass
class Context:
    events: dict[str, Dump]
    defects: list[Defect]

    def records(self, kind: str) -> list[dict]:
        dump = self.events.get(kind)
        return dump.records if dump else []


def end_of(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)


def window(day: dt.date, days: int) -> tuple[dt.datetime, dt.datetime]:
    end = end_of(day)
    return end - dt.timedelta(days=days), end


def _ts(value) -> dt.datetime | None:
    return parse_ts(value) if value else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if q == 0.5:
        return statistics.median(values)
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


# ------------------------------------------------------------------ CodeQL ---

def _alert_open_at(a: dict, at: dt.datetime) -> bool:
    created = _ts(a.get("created_at"))
    if created is None or created > at:
        return False
    for key in ("fixed_at", "dismissed_at"):
        t = _ts(a.get(key))
        if t is not None and t <= at:
            return False
    return True


def _alerts(ctx: Context, params: dict) -> list[dict]:
    tools = params.get("tools") or ["CodeQL"]
    sev = params.get("severities")
    return [a for a in ctx.records("codeql_alerts")
            if a.get("tool") in tools and (sev is None or a.get("severity") in sev)]


def codeql_open_count(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    return sum(1 for a in _alerts(ctx, params) if _alert_open_at(a, at))


def codeql_oldest_open_age_days(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    created = [_ts(a["created_at"]) for a in _alerts(ctx, params) if _alert_open_at(a, at)]
    if not created:
        return None
    return (at - min(created)).days


def codeql_fixed_per_week(ctx: Context, day: dt.date, params: dict):
    start, end = window(day, 7)
    return sum(1 for a in _alerts(ctx, params)
               if (t := _ts(a.get("fixed_at"))) is not None and start < t <= end)


# --------------------------------------------------------------- Scorecard ---

def _scorecard_at(ctx: Context, day: dt.date) -> dict | None:
    at = end_of(day)
    recs = [r for r in ctx.records("scorecard") if (t := _ts(r.get("date"))) is not None and t <= at]
    return max(recs, key=lambda r: r["date"]) if recs else None


def scorecard_score(ctx: Context, day: dt.date, params: dict):
    rec = _scorecard_at(ctx, day)
    return rec.get("score") if rec else None


def scorecard_check(ctx: Context, day: dt.date, params: dict):
    rec = _scorecard_at(ctx, day)
    if not rec:
        return None
    score = (rec.get("checks") or {}).get(params["name"])
    return None if score is None or score < 0 else score


# ---------------------------------------------------------------------- CI ---

def _verdict_runs(ctx: Context, day: dt.date, workflows: list[str]) -> list[dict]:
    start, end = window(day, 30)
    out = []
    for r in ctx.records("workflow_runs"):
        if workflows and r.get("workflow") not in workflows:
            continue
        if r.get("status") != "completed" or r.get("conclusion") not in ("success", "failure"):
            continue
        t = _ts(r.get("created_at"))
        if t is not None and start < t <= end:
            out.append(r)
    return out


def ci_pass_rate_30d(ctx: Context, day: dt.date, params: dict):
    runs = _verdict_runs(ctx, day, params.get("workflows") or [])
    if not runs:
        return None
    return sum(1 for r in runs if r["conclusion"] == "success") / len(runs)


def ci_median_wall_time_30d(ctx: Context, day: dt.date, params: dict):
    runs = _verdict_runs(ctx, day, [params["workflow"]])
    durations = [(_ts(r["updated_at"]) - _ts(r["run_started_at"])).total_seconds()
                 for r in runs if r.get("updated_at") and r.get("run_started_at")]
    return statistics.median(durations) if durations else None


# ---------------------------------------------------------------------- PRs ---

def _is_agent(pr: dict) -> bool:
    """A PR is agent-authored when GitHub reports a bot author, or its head
    ref starts with a gh-aw branch prefix (AGENT_BRANCH_PREFIXES: copilot/,
    agentics/, remediation) or contains the issue-remediation workflow's
    marker (AGENT_BRANCH_MARKER). A human driving Copilot CLI (author_type
    "User", no matching ref) counts as human — this is a branch-shape
    heuristic, not an attempt to detect AI assistance in general."""
    if (pr.get("author_type") or "").lower() == "bot":
        return True
    ref = pr.get("head_ref") or ""
    return ref.startswith(AGENT_BRANCH_PREFIXES) or AGENT_BRANCH_MARKER in ref


def _merged_prs(ctx: Context, day: dt.date, author_type: str) -> list[dict]:
    start, end = window(day, 30)
    out = []
    for pr in ctx.records("pull_requests"):
        t = _ts(pr.get("merged_at"))
        if t is None or not (start < t <= end):
            continue
        agent = _is_agent(pr)
        if author_type == "agent" and not agent or author_type == "human" and agent:
            continue
        out.append(pr)
    return out


def pr_lead_time_30d(ctx: Context, day: dt.date, params: dict):
    prs = _merged_prs(ctx, day, params.get("author_type", "all"))
    leads = [(_ts(p["merged_at"]) - _ts(p["created_at"])).total_seconds() for p in prs if p.get("created_at")]
    return _quantile(leads, float(params.get("quantile", 0.5)))


def prs_merged_30d(ctx: Context, day: dt.date, params: dict):
    return len(_merged_prs(ctx, day, params.get("author_type", "all")))


def pr_product_ratio_30d(ctx: Context, day: dt.date, params: dict):
    """Share of a merged PR's changed lines attributed to product code:
    each PR's (additions + deletions) weighted by the fraction of its
    changed files under apps/, summed over PRs merged in the trailing 30
    days. An approximation, not an exact per-line count - the event dump
    keeps file paths (spec S4.2), not which file each changed line
    belongs to, so a PR touching both product and non-product files
    splits its total lines by file-count share rather than by counting
    lines in apps/ files directly."""
    product = total = 0.0
    for pr in _merged_prs(ctx, day, "all"):
        lines = (pr.get("additions") or 0) + (pr.get("deletions") or 0)
        files = pr.get("files") or []
        if not lines or not files:
            continue
        share = sum(1 for f in files if f.startswith("apps/")) / len(files)
        product += lines * share
        total += lines
    return product / total if total else None


# ------------------------------------------------------------------- issues ---

def _labels_at(issue: dict, at: dt.datetime) -> set[str]:
    labels: set[str] = set()
    events = sorted(issue.get("label_events") or [], key=lambda e: e["at"])
    if not events:
        return set(issue.get("labels") or [])
    for e in events:
        t = _ts(e["at"])
        if t is None or t > at:
            break
        if e["event"] == "labeled":
            labels.add(e["label"])
        else:
            labels.discard(e["label"])
    return labels


def issues_open_by_label(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    label = params["label"]
    count = 0
    for issue in ctx.records("issues"):
        created = _ts(issue.get("created_at"))
        closed = _ts(issue.get("closed_at"))
        if created is None or created > at or (closed is not None and closed <= at):
            continue
        if label in _labels_at(issue, at):
            count += 1
    return count


def issues_time_to_triage_median_30d(ctx: Context, day: dt.date, params: dict):
    start, end = window(day, 30)
    samples = []
    for issue in ctx.records("issues"):
        created = _ts(issue.get("created_at"))
        removed = next((_ts(e["at"]) for e in sorted(issue.get("label_events") or [], key=lambda e: e["at"])
                        if e["event"] == "unlabeled" and e["label"] == "needs-triage"), None)
        if created and removed and start < removed <= end:
            samples.append((removed - created).total_seconds())
    return statistics.median(samples) if samples else None


# ------------------------------------------------------------------ defects ---

def defects_by_status(ctx: Context, day: dt.date, params: dict):
    wanted = params["status"]
    count = 0
    for d in ctx.defects:
        if day < d.first_seen:
            continue
        status = d.status if day >= d.status_changed else "open"
        if status == wanted:
            count += 1
    return count


DERIVATIONS: dict[str, Callable[[Context, dt.date, dict], float | None]] = {
    "codeql_open_count": codeql_open_count,
    "codeql_oldest_open_age_days": codeql_oldest_open_age_days,
    "codeql_fixed_per_week": codeql_fixed_per_week,
    "scorecard_score": scorecard_score,
    "scorecard_check": scorecard_check,
    "ci_pass_rate_30d": ci_pass_rate_30d,
    "ci_median_wall_time_30d": ci_median_wall_time_30d,
    "pr_lead_time_30d": pr_lead_time_30d,
    "prs_merged_30d": prs_merged_30d,
    "pr_product_ratio_30d": pr_product_ratio_30d,
    "issues_open_by_label": issues_open_by_label,
    "issues_time_to_triage_median_30d": issues_time_to_triage_median_30d,
    "defects_by_status": defects_by_status,
}

# R9(c): freshness per derivation, keyed off the event kinds each one reads
# (not name-prefix matching — Task 14 uses this table). An empty tuple means
# ledger-derived: defects_by_status reads only the curated defect ledger
# (part of every build's inputs, not an event dump), so it is always fresh.
DERIVATION_SOURCES: dict[str, tuple[str, ...]] = {
    "codeql_open_count": ("codeql_alerts",),
    "codeql_oldest_open_age_days": ("codeql_alerts",),
    "codeql_fixed_per_week": ("codeql_alerts",),
    "scorecard_score": ("scorecard",),
    "scorecard_check": ("scorecard",),
    "ci_pass_rate_30d": ("workflow_runs",),
    "ci_median_wall_time_30d": ("workflow_runs",),
    "pr_lead_time_30d": ("pull_requests",),
    "prs_merged_30d": ("pull_requests",),
    "pr_product_ratio_30d": ("pull_requests",),
    "issues_open_by_label": ("issues",),
    "issues_time_to_triage_median_30d": ("issues",),
    "defects_by_status": (),
}
